import os
import logging
import traceback
from fnmatch import fnmatchcase
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pmgen.io.http_client import get_service_file_bytes, _parse_unpacking_date_from_08_bytes, _parse_code_from_08_bytes, _parse_code_from_csv_bytes, get_unpacking_date
from pmgen.engine.single_report import generate_from_bytes
from datetime import datetime, date
import calendar
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from typing import Dict


class SingleReportWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, session, serial, threshold, life_basis, show_all, threshold_enabled, alerts_enabled, customer_name=""):
        super().__init__()
        self.session = session
        self.serial = serial
        self.threshold = threshold
        self.life_basis = life_basis
        self.show_all = show_all
        self.threshold_enabled = threshold_enabled
        self.alerts_enabled = alerts_enabled
        self.customer_name = customer_name

    def run(self):
        """This runs in the background thread."""
        try:
            pm_pdf_bytes = get_service_file_bytes(self.serial, option="PMSupport", sess=self.session)
            
            unpacking_date = get_unpacking_date(self.serial, sess=self.session)
            
            report_text = generate_from_bytes(
                pm_pdf_bytes=pm_pdf_bytes,
                threshold=self.threshold,
                life_basis=self.life_basis,
                show_all=self.show_all,
                threshold_enabled=self.threshold_enabled,
                unpacking_date=unpacking_date,
                alerts_enabled=self.alerts_enabled,
                customer_name=self.customer_name
            )

            self.finished.emit(report_text)

        except Exception as e:
            self.error.emit(f"Failed to generate report for {self.serial}:\n{str(e)}")

@dataclass
class BulkConfig:
    top_n: int = 25
    out_dir: str = ""
    pool_size: int = 4
    blacklist: list[str] = None
    show_all: bool = False
    custom_08_name: str = ""
    custom_08_code: int = 0
    custom_08_sub: int = 0
    custom_05_name: str = ""
    custom_05_code: int = 0
    custom_05_sub: int = 0
    generate_pdfs: bool = True
    machine_filter: str = "both"

    def __post_init__(self):
        if self.blacklist is None: self.blacklist = []
        self.machine_filter = (self.machine_filter or "both").strip().lower()
        if self.machine_filter not in {"active", "inactive", "both"}:
            self.machine_filter = "both"
        self.custom_08_sub = max(0, int(self.custom_08_sub or 0))
        self.custom_05_code = max(0, int(self.custom_05_code or 0))
        self.custom_05_sub = max(0, int(self.custom_05_sub or 0))

class BulkRunner(QObject):
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    item_updated = pyqtSignal(str, str, str, str, str, str, str, str)

    def __init__(self, cfg: BulkConfig, threshold: float, life_basis: str,
                 threshold_enabled: bool = True,
                 unpack_max_enabled: bool = False, unpack_max_months: int = 0,
                 unpack_min_enabled: bool = False, unpack_min_months: int = 0,
                 customer_map: Dict[str,str] = {}):
        super().__init__()
        self.cfg = cfg
        self.threshold = threshold
        self.life_basis = life_basis
        self.threshold_enabled = bool(threshold_enabled)
        
        self.customer_map = {
            str(serial).strip().upper(): customer_name
            for serial, customer_name in (customer_map or {}).items()
            if str(serial).strip()
        }

        self._blacklist = [p.upper() for p in (cfg.blacklist or [])]

        self._unpack_max_enabled = bool(unpack_max_enabled)
        self._unpack_max_months = max(0, min(120, int(unpack_max_months)))
        self._unpack_min_enabled = bool(unpack_min_enabled)
        self._unpack_min_months = max(0, min(120, int(unpack_min_months)))

    def _update_pool_progress(self, current, total):
        self.progress.emit(f"[Info] Creating session pool ({current}/{total})...")

    def _is_blacklisted(self, serial: str) -> bool:
        s = (serial or "").upper()
        for pat in (self._blacklist or []):
            if fnmatchcase(s, pat): return True
        return False

    def _fmt_pct(self, p):
        if p is None: return "—"
        try: return f"{(float(p) * 100):.1f}%"
        except Exception: return "—"

    def _machine_filter_label(self) -> str:
        labels = {"active": "Active", "inactive": "Inactive", "both": "Active/Inactive"}
        return labels.get(self.cfg.machine_filter, "Active/Inactive")

    def _filter_serials_by_machine_state(self, serial_status_map: Dict[str, str]) -> list[str]:
        if self.cfg.machine_filter == "both":
            return list(serial_status_map.keys())

        return [
            serial for serial, machine_status in serial_status_map.items()
            if str(machine_status).strip().lower() == self.cfg.machine_filter
        ]

    def _check_date_filter(self, d: date) -> str | None:
        """
        Returns a reason string if filtered (e.g., 'Too Old'), or None if allowed.
        """
        if not d:
            # If no date is available, we cannot filter by date, so we keep it.
            return None
        
        today = date.today()

        def _add_months(source_date: date, months: int) -> date:
            y = source_date.year + (source_date.month - 1 + months) // 12
            m = (source_date.month - 1 + months) % 12 + 1
            return date(y, m, min(source_date.day, calendar.monthrange(y, m)[1]))

        # 1. Max Age Check (Exclude if OLDER than X months)
        if self._unpack_max_enabled:
            cutoff_max = _add_months(d, self._unpack_max_months)
            # If today is AFTER the cutoff, the device is too old
            if today > cutoff_max:
                return "Too Old"

        # 2. Min Age Check (Exclude if NEWER than X months)
        if self._unpack_min_enabled:
            cutoff_min = _add_months(d, self._unpack_min_months)
            # If today is BEFORE the cutoff, the device is too new
            if today < cutoff_min:
                return "Too New"

        return None

    def run(self):
        pool = None
        try:
            if self.cfg.generate_pdfs:
                if not self.cfg.out_dir or not self.cfg.out_dir.strip():
                    raise ValueError("Output directory is not set.")

                # Create Output Directory
                date_str = datetime.now().strftime("%Y-%m-%d")
                base_path = os.path.join(self.cfg.out_dir, date_str)
                final_out_dir = base_path
                counter = 1
                while os.path.exists(final_out_dir):
                    final_out_dir = f"{base_path} ({counter})"
                    counter += 1
                os.makedirs(final_out_dir, exist_ok=True)

            from pmgen.io.http_client import SessionPool, get_serial_status_map_after_login, get_service_file_bytes, get_unpacking_date
            from pmgen.parsing.parse_pm_report import parse_pm_report
            from pmgen.engine.run_rules import run_rules
            from pmgen.engine.single_report import create_pdf_report
            from pmgen.engine.final_report import write_final_summary_pdf

            # 1. Initialize Pool
            pool_size = self.cfg.pool_size
            self.progress.emit(f"[Info] Initializing {pool_size} sessions...")

            try:
                pool = SessionPool(pool_size, callback=self._update_pool_progress)
            except Exception as e:
                self.progress.emit(f"[Info] Failed to create pool: {e}")
                return

            # 2. Get Serials
            with pool.acquire() as sess:
                serial_status_map = get_serial_status_map_after_login(sess)
                serials = self._filter_serials_by_machine_state(serial_status_map)

            self.progress.emit(f"[Info] Found {len(serials)} {self._machine_filter_label()} Serials.")

            # 3. Filter Blacklist Only (Date filtering happens during processing now)
            serials0 = list(serials or [])
            serials_to_process = [s for s in serials0 if not self._is_blacklisted(s)]

            for s in serials_to_process:
                machine_status = serial_status_map.get(s, "")
                self.item_updated.emit(s, "Queued", "", "Unknown", "", "", "", machine_status)

            if QThread.currentThread().isInterruptionRequested():
                self.finished.emit("[Info] Stopped.")
                return

            self.progress.emit(f"[Info] Processing {len(serials_to_process)} Serials...")

            thr = self.threshold
            basis = self.life_basis
            show_all = self.cfg.show_all
            thr_enabled = self.threshold_enabled

            def get_val(item, key, default=0.0):
                val = getattr(item, key, None)
                if val is not None: return val
                if isinstance(item, dict): return item.get(key, default)
                return default

            # --- WORKER FUNCTION ---
            def work(serial: str):
                machine_status = serial_status_map.get(serial, "")
                self.item_updated.emit(serial, "Processing", "...", "", "", "", "", machine_status)
                
                cust_name = self.customer_map.get(str(serial).strip().upper(), "")

                try:
                    # A. Fetch Data
                    with pool.acquire() as sess:
                        blob = get_service_file_bytes(serial, "PMSupport", sess=sess)

                        unpack_date = None
                        custom08_val = ""
                        custom05_val = ""
                        try:
                            blob_08 = get_service_file_bytes(serial, "08", sess=sess)
                            unpack_date = _parse_unpacking_date_from_08_bytes(blob_08)
                            if self.cfg.custom_08_code > 0:
                                custom08_val = _parse_code_from_csv_bytes(
                                    self.cfg.custom_08_code, self.cfg.custom_08_sub, blob_08)
                                if not custom08_val:
                                    custom08_val = "N/A"
                        except Exception:
                            pass

                        try:
                            if self.cfg.custom_05_code > 0:
                                blob_05 = get_service_file_bytes(serial, "05", sess=sess)
                                custom05_val = _parse_code_from_csv_bytes(
                                    self.cfg.custom_05_code, self.cfg.custom_05_sub, blob_05)
                                if not custom05_val:
                                    custom05_val = "N/A"
                        except Exception:
                            pass

                    # B. Parse & Calculate
                    report = parse_pm_report(blob)
                    model_name = (report.headers or {}).get("model") or "Unknown"

                    selection = run_rules(report, threshold=thr, life_basis=basis, threshold_enabled=thr_enabled)

                    meta = getattr(selection, "meta", {}) or {}
                    all_items = meta.get("all_items", []) or meta.get("all", []) or getattr(selection, "all_items", []) or []
                    best_used = max([float(get_val(f, "life_used", 0.0) or 0.0) for f in all_items], default=0.0)
                    
                    pct_str = self._fmt_pct(best_used)
                    d_str = unpack_date.strftime("%Y-%m-%d") if unpack_date else ""

                    # C. Check Date Filter
                    filter_reason = self._check_date_filter(unpack_date)

                    if filter_reason:
                        # FILTERED: Update UI with percentage, but mark as filtered.
                        # We do NOT generate the individual PDF report.
                        self.item_updated.emit(serial, "Filtered", pct_str, model_name, d_str, custom08_val, custom05_val, machine_status)
                        
                        return {
                            "serial": serial,
                            "filtered": True,
                            "reason": filter_reason,
                            "best_used": float(best_used) # Return value so we can sort if needed
                        }
                    else:
                        if self.cfg.generate_pdfs:
                            create_pdf_report(
                                report=report, selection=selection, threshold=thr, life_basis=basis,
                                show_all=show_all, out_dir=final_out_dir, threshold_enabled=thr_enabled,
                                unpacking_date=unpack_date,
                                customer_name=cust_name
                            )

                        self.item_updated.emit(serial, "Done", pct_str, model_name, d_str, custom08_val, custom05_val, machine_status)

                        return {
                            "serial": (report.headers or {}).get("serial") or serial,
                            "model": model_name,
                            "best_used": float(best_used),
                            "text": "None",
                            "customer_name": cust_name, 
                            "grouped": meta.get("selection_pn_grouped", {}) or {},
                            "flat": meta.get("selection_pn", {}) or {},
                            "kit_by_pn": meta.get("kit_by_pn", {}) or {},
                            "due_sources": meta.get("due_sources", {}) or {},
                            "unpacking_date": unpack_date,
                            "filtered": False
                        }

                except Exception as e:
                    self.item_updated.emit(serial, "Failed", str(e), "", "", "", "", machine_status)
                    return {"serial": serial, "error": str(e), "trace": traceback.format_exc()}

            # --- EXECUTION LOOP ---
            results = []
            completed_count = 0
            total_work = len(serials_to_process)

            if total_work > 0:
                with ThreadPoolExecutor(max_workers=self.cfg.pool_size) as ex:
                    futures = {ex.submit(work, s): s for s in serials_to_process}
                    
                    for fut in as_completed(futures):
                        if QThread.currentThread().isInterruptionRequested():
                            self.progress.emit("[Info] Stop requested. Cancelling pending tasks...")
                            for f in futures:
                                f.cancel()
                            break
                        
                        s = futures[fut]
                        completed_count += 1
                        self.progress_value.emit(completed_count, total_work)

                        try:
                            res = fut.result()
                            if "error" in res:
                                self.progress.emit(f"[Bulk] {s}: ERROR — {res['error']}")
                            elif res.get("filtered"):
                                # Log as filtered but show the percentage
                                self.progress.emit(f"[Bulk] {s}: FILTERED ({res['reason']}) — {self._fmt_pct(res.get('best_used'))}")
                            else:
                                self.progress.emit(f"[Bulk] {s}: OK — {self._fmt_pct(res['best_used'])}")
                            results.append(res)
                        except Exception as e:
                            self.progress.emit(f"[Bulk] {s}: CRITICAL — {e}")
            else:
                self.progress.emit("[Info] No serials to process.")
            
            if QThread.currentThread().isInterruptionRequested():
                 self.finished.emit("[Info] Process Stopped by User.")
                 return

            # --- POST-PROCESSING ---
            # Exclude Filtered items from the Final PDF Summary
            ok = [r for r in results if "error" not in r and not r.get("filtered", False)]
            ok.sort(key=lambda r: (r.get("best_used") or 0.0), reverse=True)
            top = ok[: self.cfg.top_n]

            if len(top) > 0:
                if self.cfg.generate_pdfs:
                    self.progress.emit(f"[Info] Wrote {len(top)} report files to: {final_out_dir}")
                    try:
                        pdf_path = write_final_summary_pdf(
                            out_dir=final_out_dir, results=results, top=top, thr=thr, basis=basis,
                            filename="Final_Summary.pdf", threshold_enabled=thr_enabled
                        )
                        self.finished.emit(f"[Info] Complete. Summary written to: {pdf_path}")
                    except Exception as e:
                        self.finished.emit(f"[Info] Reports generated, but Summary PDF failed: {e}")
                else:
                    self.finished.emit("[Info] Complete. Table populated (PDF generation disabled).")
            else:
                self.finished.emit("[Info] Complete (No valid reports generated).")

        except Exception as e:
            self.finished.emit(f"[Info] Failed: {e}")
            traceback.print_exc()
        finally:
            if pool:
                try: pool.close()
                except: pass