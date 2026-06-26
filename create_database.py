import sqlite3
import re
import types
from typing import Dict, Pattern
from pmgen.catalog.part_kit_catalog import PmUnit, Catalog, Model


##  THIS FILE IS NOW USED TO GENERATE THE DATABASE ENTRIES FOR THE CANON MAPPINGS, PMUNITS, KITS, AND CATALOGS.
##  IMPORTANT:
##      SOME MODELS USE THE MONIKER LCF AND TLCF INTERCHANGABLY. SO WHEN BUILDING PMUNITS, KITS, AND CATALOGS. BE SURE TO
##      REFRENCE THE PM SUPPORT PAGE FROM ECC FIRST TO KNOW IF THAT MODEL USES LCF OR TLCF MONIKER.

SPC   = r"\s*"
LP    = r"\(?"
RP    = r"\)?"
COLOR = r"(?P<chan>K|C|M|Y)"

CANON = types.SimpleNamespace(
    # Color parts (order doesn’t matter; names used for dynamic lookup)
    Y_DRUM = "DRUM[Y]",
    M_DRUM = "DRUM[M]",
    C_DRUM = "DRUM[C]",
    K_DRUM = "DRUM[K]",

    Y_DRUM_BLADE = "DRUM BLADE[Y]",
    M_DRUM_BLADE = "DRUM BLADE[M]",
    C_DRUM_BLADE = "DRUM BLADE[C]",
    K_DRUM_BLADE = "DRUM BLADE[K]",

    Y_CHARGER_NEEDLE = "MAIN CHARGER NEEDLE[Y]",
    M_CHARGER_NEEDLE = "MAIN CHARGER NEEDLE[M]",
    C_CHARGER_NEEDLE = "MAIN CHARGER NEEDLE[C]",
    K_CHARGER_NEEDLE = "MAIN CHARGER NEEDLE[K]",

    Y_GRID = "GRID[Y]",
    M_GRID = "GRID[M]",
    C_GRID = "GRID[C]",
    K_GRID = "GRID[K]",

    Y_CLEANING_PAD = "CHARGER CLEANING PAD[Y]",
    M_CLEANING_PAD = "CHARGER CLEANING PAD[M]",
    C_CLEANING_PAD = "CHARGER CLEANING PAD[C]",
    K_CLEANING_PAD = "CHARGER CLEANING PAD[K]",

    Y_DEVELOPER = "DEVELOPER[Y]",
    M_DEVELOPER = "DEVELOPER[M]",
    C_DEVELOPER = "DEVELOPER[C]",
    K_DEVELOPER = "DEVELOPER[K]",

    # Generic parts (mono / non-color-specific)
    BELT_BLADE = "BELT BLADE",
    FUSER_BELT = "FUSER BELT",
    PRESS_ROLLER = "PRESS ROLLER",
    PRESS_ROLLER_FINGER = "PRESS ROLLER FINGER",
    FUSER_PAD = "FUSER PAD",
    OIL_SLIDE_SHEET = "OIL/SLIDE SHEET",
    OZONE_FILTER = "OZONE FILTER",
    TONER_FILTER = "TONER FILTER",
    TRANSFER_ROLLER = "TRANSFER ROLLER",

    # Mono (A-line) expand-to-K channel
    MONO_DRUM = "DRUM[K]",
    MONO_DRUM_BLADE = "DRUM BLADE[K]",
    MONO_DEVELOPER = "DEVELOPER[K]",
    MONO_GRID = "GRID[K]",
    MONO_CHARGER_NEEDLE = "MAIN CHARGER NEEDLE[K]",

    # Fuser / transfer / misc
    FUSER_ROLLER = "FUSER ROLLER",
    SEPARATION_FINGER_DRUM  = "SEPARATION FINGER (DRUM)",
    SEPARATION_FINGER_FUSER = "SEPARATION FINGER (FUSER)",
    OZONE_FILTER_1 = "OZONE FILTER 1",
    OZONE_FILTER_2 = "OZONE FILTER 2",
    VOC_FILTER = "VOC FILTER",
    TRANSFER_BELT = "TRANSFER BELT",
    HEAT_ROLLER = "HEAT ROLLER",

    # DF generic
    DF_FEED_ROLLER = "DF FEED ROLLER",
    DF_PICK_UP_ROLLER = "DF PICK UP ROLLER",
    DF_SEP_ROLLER = "DF SEP ROLLER",

    # Cassette/bypass/LCF positions — keep punctuation/spaces exactly
    FEED_1ST_CST = "FEED ROLLER (1st CST.)",
    FEED_2ND_CST = "FEED ROLLER (2nd CST.)",
    FEED_3RD_CST = "FEED ROLLER (3rd CST.)",
    FEED_4TH_CST = "FEED ROLLER (4th CST.)",
    FEED_SFB = "FEED ROLLER (SFB/BYPASS)",
    FEED_LCF = "FEED ROLLER (LCF)",
    FEED_OLCF = "FEED ROLLER (O-LCF)",
    FEED_O2LCF = "FEED ROLLER (O2-LCF)",
    FEED_TLCF = "FEED ROLLER (T-LCF)",

    PICK_1ST_CST = "PICK UP ROLLER (1st CST.)",
    PICK_2ND_CST = "PICK UP ROLLER (2nd CST.)",
    PICK_3RD_CST = "PICK UP ROLLER (3rd CST.)",
    PICK_4TH_CST = "PICK UP ROLLER (4th CST.)",
    PICK_SFB = "PICK UP ROLLER/PAD (SFB/BYPASS)",
    PICK_LCF = "PICK UP ROLLER (LCF)",
    PICK_OLCF = "PICK UP ROLLER (O-LCF)",
    PICK_O2LCF = "PICK UP ROLLER (O2-LCF)",
    PICK_TLCF = "PICK UP ROLLER (T-LCF)",

    SEP_1ST_CST = "SEP ROLLER/PAD (1st CST.)",
    SEP_2ND_CST = "SEP ROLLER/PAD (2nd CST.)",
    SEP_3RD_CST = "SEP ROLLER/PAD (3rd CST.)",
    SEP_4TH_CST = "SEP ROLLER/PAD (4th CST.)",
    SEP_SFB = "SEP ROLLER/PAD (SFB/BYPASS)",
    SEP_LCF = "SEP ROLLER/PAD (LCF)",
    SEP_OLCF = "SEP ROLLER/PAD (O-LCF)",
    SEP_O2LCF = "SEP ROLLER/PAD (O2-LCF)",
    SEP_TLCF = "SEP ROLLER/PAD (T-LCF)",

    PICK_FEED_DSDF_COMBO = "PICK UP ROLLER/FEED ROLLER(DSDF)",
)

CANON_MAP: Dict[Pattern[str], str] = {
    # ─── Color channels ─────────────────────────────────────────────
    re.compile(rf"^DRUM{SPC}{LP}{COLOR}{RP}$", re.I):                "DRUM[{chan}]",
    re.compile(rf"^DRUM{SPC}BLADE{SPC}{LP}{COLOR}{RP}$", re.I):      "DRUM BLADE[{chan}]",
    re.compile(rf"^(?:MAIN{SPC})?CHARGER{SPC}NEEDLE{SPC}{LP}{COLOR}{RP}$", re.I): "MAIN CHARGER NEEDLE[{chan}]",
    re.compile(rf"^GRID{SPC}{LP}{COLOR}{RP}$", re.I):                "GRID[{chan}]",
    re.compile(rf"^CHARGER{SPC}CLEANING{SPC}PAD{SPC}{LP}{COLOR}{RP}$", re.I): "CHARGER CLEANING PAD[{chan}]",
    re.compile(r"^BLACK\s+DEVELOPER$", re.I):                        CANON.K_DEVELOPER,
    re.compile(r"^CYAN\s+DEVELOPER$", re.I):                         CANON.C_DEVELOPER,
    re.compile(r"^MAGENTA\s+DEVELOPER$", re.I):                      CANON.M_DEVELOPER,
    re.compile(r"^YELLOW\s+DEVELOPER$", re.I):                       CANON.Y_DEVELOPER,

    # ─── Generic parts ─────────────────────────────────────────────
    re.compile(r"^(BELT|RECOVERY)\s+BLADE$", re.I):                  CANON.BELT_BLADE,
    re.compile(r"^FUSER\s+BELT$", re.I):                             CANON.FUSER_BELT,
    re.compile(r"^PRESS\s+ROLLER$", re.I):                           CANON.PRESS_ROLLER,
    re.compile(r"^PRESS\s+ROLLER\s+FINGER$", re.I):                  CANON.PRESS_ROLLER_FINGER,
    re.compile(r"^FUSER\s+PAD$", re.I):                              CANON.FUSER_PAD,
    re.compile(r"^(?:OIL\s+RECOVERY|SLIDE)\s+SHEET$", re.I):         CANON.OIL_SLIDE_SHEET,
    re.compile(r"^OZONE\s+FILTER(?:\s*\(?REAR\)?)?$", re.I):         CANON.OZONE_FILTER,
    re.compile(r"^TONER\s+FILTER$", re.I):                           CANON.TONER_FILTER,
    re.compile(r"^(?:2(?:ND)?\s*)?TRANSFER\s+ROLLER$", re.I):        CANON.TRANSFER_ROLLER,

    # ─── Document Feeder types ──────────────────────────────────────
    re.compile(r"^FEED\s+ROLLER\s*\((?:DF|RADF|DSDF)\)$", re.I):     CANON.DF_FEED_ROLLER,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\((?:DF|RADF|DSDF)\)$", re.I):CANON.DF_PICK_UP_ROLLER,
    re.compile(r"^SEP(?:ARATION)?\s+ROLLER\s*\((?:DF|RADF|DSDF)\)$", re.I): CANON.DF_SEP_ROLLER,

    # ─── Individual cassette / bypass / LCF feed types ──────────────
    re.compile(r"^FEED\s+ROLLER\s*\(1st\s*CST\.?\)$", re.I):         CANON.FEED_1ST_CST,
    re.compile(r"^FEED\s+ROLLER\s*\(2nd\s*CST\.?\)$", re.I):         CANON.FEED_2ND_CST,
    re.compile(r"^FEED\s+ROLLER\s*\(3rd\s*CST\.?\)$", re.I):         CANON.FEED_3RD_CST,
    re.compile(r"^FEED\s+ROLLER\s*\(4th\s*CST\.?\)$", re.I):         CANON.FEED_4TH_CST,
    re.compile(r"^FEED\s+ROLLER\s*\((?:SFB|BYPASS)\)$", re.I):       CANON.FEED_SFB,
    re.compile(r"^FEED\s+ROLLER\s*\(LCF\)$", re.I):                  CANON.FEED_LCF,
    re.compile(r"^FEED\s+ROLLER\s*\(O-?LCF\)$", re.I):               CANON.FEED_OLCF,
    re.compile(r"^FEED\s+ROLLER\s*\(O2-?LCF\)$", re.I):              CANON.FEED_O2LCF,
    re.compile(r"^FEED\s+ROLLER\s*\(T-?LCF\)$", re.I):               CANON.FEED_TLCF,

    # ─── Same expansion for PICK UP and SEP rollers ─────────────────
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\(1st\s*CST\.?\)$", re.I):    CANON.PICK_1ST_CST,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\(2nd\s*CST\.?\)$", re.I):    CANON.PICK_2ND_CST,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\(3rd\s*CST\.?\)$", re.I):    CANON.PICK_3RD_CST,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\(4th\s*CST\.?\)$", re.I):    CANON.PICK_4TH_CST,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\((?:SFB|BYPASS)\)$", re.I):  CANON.PICK_SFB,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\(LCF\)$", re.I):             CANON.PICK_LCF,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\(O-?LCF\)$", re.I):          CANON.PICK_OLCF,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\(O2-?LCF\)$", re.I):         CANON.PICK_O2LCF,
    re.compile(r"^PICK\s+UP\s+ROLLER\s*\(T-?LCF\)$", re.I):          CANON.PICK_TLCF,

    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\(1st\s*CST\.?\)$", re.I): CANON.SEP_1ST_CST,
    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\(2nd\s*CST\.?\)$", re.I): CANON.SEP_2ND_CST,
    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\(3rd\s*CST\.?\)$", re.I): CANON.SEP_3RD_CST,
    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\(4th\s*CST\.?\)$", re.I): CANON.SEP_4TH_CST,
    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\((?:SFB|BYPASS)\)$", re.I): CANON.SEP_SFB,
    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\(LCF\)$", re.I):          CANON.SEP_LCF,
    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\(O-?LCF\)$", re.I):       CANON.SEP_OLCF,
    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\(O2-?LCF\)$", re.I):      CANON.SEP_O2LCF,
    re.compile(r"^SEP(?:ARATION)?\s+(?:ROLLER|PAD)\s*\(T-?LCF\)$", re.I):       CANON.SEP_TLCF,

    re.compile(r"^PICK\s+UP\s+ROLLER\s*/\s*FEED\s+ROLLER\s*\(DSDF\)$", re.I):   CANON.PICK_FEED_DSDF_COMBO,

    # ─── Mono families (A-line) use K channel ───────────────────────
    re.compile(r"^DRUM$", re.I):                                     CANON.K_DRUM,
    re.compile(r"^DRUM\s+BLADE$", re.I):                             CANON.K_DRUM_BLADE,
    re.compile(r"^DEVELOPER$", re.I):                                CANON.K_DEVELOPER,
    re.compile(r"^GRID$", re.I):                                     CANON.K_GRID,
    re.compile(r"^(?:NEEDLE\s+ELECTRODE|MAIN\s+CHARGER\s+NEEDLE)$", re.I): CANON.K_CHARGER_NEEDLE,

    # ─── Misc mono + fuser/transfer parts ───────────────────────────
    re.compile(r"^FUSER\s+ROLLER$", re.I):                           CANON.FUSER_ROLLER,
    re.compile(r"^SEPARATION\s+FINGER\(DRUM\)$", re.I):              CANON.SEPARATION_FINGER_DRUM,
    re.compile(r"^SEPARATION\s+FINGER\(FUSER\)$", re.I):             CANON.SEPARATION_FINGER_FUSER,

    # ─── Misc filters and sheets ────────────────────────────────────
    re.compile(r"^OZONE\s+FILTER\s*1$", re.I):                       CANON.OZONE_FILTER_1,
    re.compile(r"^OZONE\s+FILTER\s*2$", re.I):                       CANON.OZONE_FILTER_2,
    re.compile(r"^VOC\s+FILTER$", re.I):                             CANON.VOC_FILTER,
    re.compile(r"^TRANSFER\s+BELT$", re.I):                          CANON.TRANSFER_BELT,
    re.compile(r"^HEAT\s+ROLLER$", re.I):                            CANON.HEAT_ROLLER,
}

# Parts and Kits

# 330AC / 400AC
EPU_FC330_K = PmUnit("EPU-FC330-K", [
    CANON.K_DRUM,
    CANON.K_DRUM_BLADE,
    CANON.K_CHARGER_NEEDLE,
    CANON.K_GRID,
    CANON.K_CLEANING_PAD,
    CANON.K_DEVELOPER
])
EPU_FC330_Y = PmUnit("EPU-FC330-Y", [
    CANON.Y_DRUM,
    CANON.Y_DRUM_BLADE,
    CANON.Y_CHARGER_NEEDLE,
    CANON.Y_GRID,
    CANON.Y_CLEANING_PAD,
    CANON.Y_DEVELOPER
])
EPU_FC330_M = PmUnit("EPU-FC330-M", [
    CANON.M_DRUM,
    CANON.M_DRUM_BLADE,
    CANON.M_CHARGER_NEEDLE,
    CANON.M_GRID,
    CANON.M_CLEANING_PAD,
    CANON.M_DEVELOPER,
])
EPU_FC330_C = PmUnit("EPU-FC330-C", [
    CANON.C_DRUM,
    CANON.C_DRUM_BLADE,
    CANON.C_CHARGER_NEEDLE,
    CANON.C_GRID,
    CANON.C_CLEANING_PAD,
    CANON.C_DEVELOPER,
])    
TR_BLT_CLN_FC330_O = PmUnit("TR-BLT_CLN-FC330-O", [
    CANON.BELT_BLADE
])
TR_FC330_O = PmUnit("TR-FC330-O", [
    CANON.TRANSFER_ROLLER
])
FUSER_FC330_120 = PmUnit("FUSER-FC330-120", [
    CANON.FUSER_BELT,
    CANON.PRESS_ROLLER,
    CANON.FUSER_PAD,
    CANON.OIL_SLIDE_SHEET,
    CANON.HEAT_ROLLER,
])
ROLL_DR_FC330_O = PmUnit("ROLL-DR-FC330-O", [
    CANON.FEED_1ST_CST,
    CANON.PICK_1ST_CST,
    CANON.SEP_1ST_CST,
    CANON.FEED_2ND_CST,
    CANON.PICK_2ND_CST,
    CANON.SEP_2ND_CST,
    CANON.FEED_3RD_CST,
    CANON.PICK_3RD_CST,
    CANON.SEP_3RD_CST,
    CANON.FEED_4TH_CST,
    CANON.PICK_4TH_CST,
    CANON.SEP_4TH_CST,
])
ROLL_LR_FC330_O = PmUnit("ROLL-LR-FC330-O", [
    CANON.FEED_LCF, #VERIFY
    CANON.PICK_LCF,
    CANON.SEP_LCF,
])
ROLL_DF_FC330_O = PmUnit("ROLL-DF-FC330-O", [
    CANON.DF_FEED_ROLLER,
    CANON.DF_PICK_UP_ROLLER,
    CANON.DF_SEP_ROLLER
])
ROLL_BR_FC330_O = PmUnit("ROLL-BR-FC330-O", [
    CANON.FEED_SFB,
    CANON.PICK_SFB,
    CANON.SEP_SFB
])
FILTER_OZN_KCH_A08K = PmUnit("FILTER-OZN-KCH-A08K", [
    CANON.OZONE_FILTER
])
TR_BLT_FC330 = PmUnit("TR-BLT-FC330", [
    CANON.TRANSFER_BELT
])
# 2020AC / 2520AC
DEV_KIT_FC200CLR = PmUnit("DEV-KIT-FC200CLR", [
    CANON.Y_DRUM_BLADE,
    CANON.Y_CHARGER_NEEDLE,
    CANON.Y_GRID,
    CANON.Y_CLEANING_PAD,
    CANON.Y_DEVELOPER,
    CANON.M_DRUM_BLADE,
    CANON.M_CHARGER_NEEDLE,
    CANON.M_GRID,
    CANON.M_CLEANING_PAD,
    CANON.M_DEVELOPER,
    CANON.C_DRUM_BLADE,
    CANON.C_CHARGER_NEEDLE,
    CANON.C_GRID,
    CANON.C_CLEANING_PAD,
    CANON.C_DEVELOPER,
])
DEV_KIT_FC200K = PmUnit("DEV-KIT-FC200K", [
    CANON.K_DRUM_BLADE,
    CANON.K_CHARGER_NEEDLE,
    CANON.K_GRID,
    CANON.K_CLEANING_PAD,
    CANON.K_DEVELOPER
])
OD_FC30N = PmUnit("OD-FC30N", [
    CANON.Y_DRUM,
    CANON.M_DRUM,
    CANON.C_DRUM,
    CANON.K_DRUM,
])
D_FC30_Y = PmUnit("D-FC30-Y", [
    CANON.Y_DEVELOPER
])
D_FC30_M = PmUnit("D-FC30-M", [
    CANON.M_DEVELOPER
])
D_FC30_C = PmUnit("D-FC30-C", [
    CANON.C_DEVELOPER
])
D_FC30_K = PmUnit("D-FC30-K", [
    CANON.K_DEVELOPER
])
CR_FC30TR2 = PmUnit("CR-FC30TR2", [
    CANON.TRANSFER_ROLLER
])
ROL_KIT_FC30_U = PmUnit("ROL-KIT-FC30-U", [
    CANON.FEED_1ST_CST,
    CANON.PICK_1ST_CST,
    CANON.SEP_1ST_CST,
    CANON.FEED_2ND_CST,
    CANON.PICK_2ND_CST,
    CANON.SEP_2ND_CST,
    CANON.FEED_3RD_CST,
    CANON.PICK_3RD_CST,
    CANON.SEP_3RD_CST,
    CANON.FEED_4TH_CST,
    CANON.PICK_4TH_CST,
    CANON.SEP_4TH_CST,
])
ROL_KIT_KD_1073 = PmUnit("ROL-KIT-KD-1073", [
    CANON.FEED_LCF,
    CANON.PICK_LCF,
    CANON.SEP_LCF,
])
# DF_KIT_3031 = PmUnit("DF-KIT-3031", [ # RSDF
#     CANON.DF_FEED_ROLLER,
#     CANON.DF_PICK_UP_ROLLER,
#     CANON.DF_SEP_ROLLER,
# ])
# This is removed from the database because it now detects the RSDF through the RSDF DETECTION RULE.
ASYS_ROL_SFB_H21X = PmUnit("ASYS-ROL-SFB-H21X", [
    CANON.FEED_SFB
])
ASYS_ROL_SPT_SFB_H373 = PmUnit("ASYS-ROL-SPT-SFB-H373", [
    CANON.SEP_SFB
])

# 2515AC / 3015AC / 3515AC / 4515AC / 5015AC

EPU_KIT_FC505CLR = PmUnit("EPU-KIT-FC505CLR", [
    CANON.Y_DRUM_BLADE,
    CANON.Y_CHARGER_NEEDLE,
    CANON.Y_GRID,
    CANON.Y_CLEANING_PAD,
    CANON.M_DRUM_BLADE,
    CANON.M_CHARGER_NEEDLE,
    CANON.M_GRID,
    CANON.M_CLEANING_PAD,
    CANON.C_DRUM_BLADE,
    CANON.C_CHARGER_NEEDLE,
    CANON.C_GRID,
    CANON.C_CLEANING_PAD,
])
DEV_KIT_FC505K = PmUnit("DEV-KIT-FC505K", [
    CANON.K_DEVELOPER,
    CANON.K_DRUM_BLADE,
    CANON.K_GRID,
    CANON.K_CLEANING_PAD,
    CANON.K_CHARGER_NEEDLE
])
TBU_KIT_FC50 = PmUnit("TBU-KIT-FC50", [
    CANON.BELT_BLADE
])
FR_KIT_FC505H = PmUnit("FR-KIT-FC505H", [ # 4515AC / 5015AC
    CANON.FUSER_BELT,
    CANON.PRESS_ROLLER,
    CANON.PRESS_ROLLER_FINGER,
    CANON.FUSER_PAD,
    CANON.OIL_SLIDE_SHEET,
])
FR_KIT_FC505 = PmUnit("FR-KIT-FC505", [ # 2515AC / 3015AC / 3515AC
    CANON.FUSER_BELT,
    CANON.PRESS_ROLLER,
    CANON.PRESS_ROLLER_FINGER,
    CANON.FUSER_PAD,
    CANON.OIL_SLIDE_SHEET,
])
OD_FC50 = PmUnit("OD-FC50", [
    CANON.Y_DRUM,
    CANON.M_DRUM,
    CANON.C_DRUM,
])
OD_FC505 = PmUnit("OD-FC505", [
    CANON.K_DRUM
])
D_FC505_Y = PmUnit("D-FC505-Y", [
    CANON.Y_DEVELOPER
])
D_FC505_M = PmUnit("D-FC505-M", [
    CANON.M_DEVELOPER
])

D_FC505_C = PmUnit("D-FC505-C", [
    CANON.C_DEVELOPER
])

D_FC505_K = PmUnit("D-FC505-K", [
    CANON.K_DEVELOPER
])
FILTER_OZN_KCH_A08K = FILTER_OZN_KCH_A08K
CR_FC30TR2 = CR_FC30TR2
ROL_KIT_FC30_U = ROL_KIT_FC30_U
ROL_KIT_1026 = PmUnit("ROL-KIT-1026", [
    CANON.FEED_LCF,
    CANON.PICK_LCF,
    CANON.SEP_LCF,
])
KIT_ROL_DSDF = PmUnit("KIT-ROL-DSDF", [
    CANON.DF_FEED_ROLLER,
    CANON.DF_PICK_UP_ROLLER,
    CANON.DF_SEP_ROLLER
])
DF_KIT_3031_FALLBACK = PmUnit("DF-KIT-3031", []) # RSDF
ASYS_ROL_SFB_H21X = PmUnit("ASYS-ROL-SFB-H21X", [
    CANON.FEED_SFB,
])
ASYS_ROL_SPT_SFB_H373 = PmUnit("ASYS-ROL-SPT-SFB-H373", [
    CANON.SEP_SFB
])

# 2525AC / 3025AC / 3525AC / 4525AC / 5525AC / 6525AC

EPU_KIT_FC425CLR = PmUnit("EPU-KIT-FC425CLR", [
    CANON.Y_DRUM_BLADE,
    CANON.Y_CHARGER_NEEDLE,
    CANON.Y_GRID,
    CANON.Y_CLEANING_PAD,
    CANON.M_DRUM_BLADE,
    CANON.M_CHARGER_NEEDLE,
    CANON.M_GRID,
    CANON.M_CLEANING_PAD,
    CANON.C_DRUM_BLADE,
    CANON.C_CHARGER_NEEDLE,
    CANON.C_GRID,
    CANON.C_CLEANING_PAD,
])
DEV_KIT_FC425K = PmUnit("DEV-KIT-FC425K", [
    CANON.K_DEVELOPER,
    CANON.K_DRUM_BLADE,
    CANON.K_GRID,
    CANON.K_CLEANING_PAD,
    CANON.K_CHARGER_NEEDLE
])
TBU_KIT_FC50 = TBU_KIT_FC50
FR_KIT_FC6525 = PmUnit("FR-KIT-FC6525", [ # 5525AC / 6525AC
    CANON.FUSER_BELT,
    CANON.PRESS_ROLLER,
    CANON.PRESS_ROLLER_FINGER,
    CANON.FUSER_PAD,
    CANON.OIL_SLIDE_SHEET,
])
FR_KIT_FC505H = FR_KIT_FC505H # 4525AC
FR_KIT_FC3525 = PmUnit("FR-KIT-FC3525", [ # 2515AC / 3015AC / 3515AC
    CANON.FUSER_BELT,
    CANON.PRESS_ROLLER,
    CANON.PRESS_ROLLER_FINGER,
    CANON.FUSER_PAD,
    CANON.OIL_SLIDE_SHEET,
])
OD_FC50 = OD_FC50
OD_FC505 = OD_FC505
D_FC425_Y = PmUnit("D-FC425-Y", [
    CANON.Y_DEVELOPER
])
D_FC425_M = PmUnit("D-FC425-M", [
    CANON.M_DEVELOPER
])

D_FC425_C = PmUnit("D-FC425-C", [
    CANON.C_DEVELOPER
])

D_FC425_K = PmUnit("D-FC425-K", [
    CANON.K_DEVELOPER
])
FILTER_OZN_KCH_A08K_X2 = PmUnit("FILTER-OZN-KCH-A08K-X2", [
    CANON.OZONE_FILTER
])
CR_FC30TR2 = CR_FC30TR2
ROL_KIT_FC30_U = ROL_KIT_FC30_U
ROL_KIT_MP_2002 = PmUnit("ROL-KIT-MP-2002", [
    CANON.FEED_OLCF,
    CANON.SEP_OLCF,
    CANON.PICK_OLCF,
])
ROL_KIT_KD_1073 = PmUnit("ROL-KIT-KD-1073", [
    CANON.FEED_LCF,
    CANON.PICK_LCF,
    CANON.SEP_LCF,
])
KIT_ROL_MR_4010 = PmUnit("KIT-ROL-MR-4010", [
    CANON.DF_FEED_ROLLER,
    CANON.DF_PICK_UP_ROLLER,
    CANON.DF_SEP_ROLLER
])
DF_KIT_3031_FALLBACK = DF_KIT_3031_FALLBACK # RSDF
ASYS_ROLL_FEED_SFB_H44X = PmUnit("ASYS-ROLL-FEED-SFB-H44X", [
    CANON.FEED_SFB,
])
ASYS_ROL_SPT_SFB_H373 = PmUnit("ASYS-ROLL-SPT-H44X", [
    CANON.SEP_SFB
])

# 5516AC / 5616AC / 6516AC / 6616AC / 7516AC / 7616AC

FR_KIT_FC556_FU = PmUnit("FR-KIT-FC556-FU", [
    CANON.FUSER_BELT,
    CANON.PRESS_ROLLER,
    CANON.PRESS_ROLLER_FINGER,
    CANON.FUSER_PAD,
    CANON.OIL_SLIDE_SHEET,
])
EPU_KIT_FC556_G_Y = PmUnit("EPU-KIT-FC556-G", [
    CANON.Y_DRUM_BLADE,
    CANON.Y_CHARGER_NEEDLE,
    CANON.Y_GRID,
    CANON.Y_CLEANING_PAD,
])
EPU_KIT_FC556_G_M = PmUnit("EPU-KIT-FC556-G", [
    CANON.M_DRUM_BLADE,
    CANON.M_CHARGER_NEEDLE,
    CANON.M_GRID,
    CANON.M_CLEANING_PAD,
])
EPU_KIT_FC556_G_C = PmUnit("EPU-KIT-FC556-G", [
    CANON.C_DRUM_BLADE,
    CANON.C_CHARGER_NEEDLE,
    CANON.C_GRID,
    CANON.C_CLEANING_PAD,
])
EPU_KIT_FC556_G_K = PmUnit("EPU-KIT-FC556-G", [
    CANON.K_DRUM_BLADE,
    CANON.K_CHARGER_NEEDLE,
    CANON.K_GRID,
    CANON.K_CLEANING_PAD,
])
EPU_KIT_FC556_S = PmUnit("EPU-KIT-FC556-S", [
    CANON.K_DRUM_BLADE,
    CANON.K_CHARGER_NEEDLE,
    CANON.K_GRID,
    CANON.K_CLEANING_PAD,
])
OD_FC556 = PmUnit("OD-FC556", [
    CANON.Y_DRUM,
    CANON.M_DRUM,
    CANON.C_DRUM,
    CANON.K_DRUM
])
CR_FC556TR2 = PmUnit("CR-FC556TR2", [
    CANON.TRANSFER_ROLLER
])
TBU_KIT_FC556 = PmUnit("TBU-KIT-FC556", [
    CANON.BELT_BLADE
])
FLTR_KIT_FC556 = PmUnit("FLTR-KIT-FC556", [
    CANON.OZONE_FILTER_1,
    CANON.OZONE_FILTER_2,
    CANON.VOC_FILTER,
    CANON.TONER_FILTER
])
ROL_KIT_FC75 = PmUnit("ROL-KIT-FC75",[
    CANON.FEED_1ST_CST,
    CANON.PICK_1ST_CST,
    CANON.SEP_1ST_CST,
    CANON.FEED_2ND_CST,
    CANON.PICK_2ND_CST,
    CANON.SEP_2ND_CST,
    CANON.FEED_3RD_CST,
    CANON.PICK_3RD_CST,
    CANON.SEP_3RD_CST,
    CANON.FEED_4TH_CST,
    CANON.PICK_4TH_CST,
    CANON.SEP_4TH_CST,
])
ROL_KIT_FC75_U = PmUnit("ROL-KIT-FC75-U", [
    CANON.FEED_TLCF,
    CANON.PICK_TLCF,
    CANON.SEP_TLCF
])
KIT_ROL_DSDF = KIT_ROL_DSDF
DF_KIT_3031_FALLBACK = DF_KIT_3031_FALLBACK # RSDF
ROL_KIT_MP2502_U = PmUnit("ROL-KIT-MP2502-U", [
    CANON.FEED_OLCF,
    CANON.PICK_OLCF,
    CANON.SEP_OLCF
])
K_RLR_FEED_SFB = PmUnit("K-RLR-FEED-SFB", [
    CANON.FEED_SFB
])
K_ROLL_PICK_BYP = PmUnit("K-ROLL-PICK-BYP", [
    CANON.PICK_SFB
])

# 6526AC / 6527AC / 7527AC

FR_KIT_FC556_FU = FR_KIT_FC556_FU
EPU_KIT_FC556_G_C = EPU_KIT_FC556_G_C
EPU_KIT_FC556_G_Y = EPU_KIT_FC556_G_Y
EPU_KIT_FC556_G_M = EPU_KIT_FC556_G_M
EPU_KIT_FC556_G_K = EPU_KIT_FC556_G_K
EPU_KIT_FC556_S = EPU_KIT_FC556_S
OD_FC556 = OD_FC556
TBU_KIT_FC556 = TBU_KIT_FC556
CR_FC556TR2 = CR_FC556TR2
FLTR_KIT_FC652 = PmUnit("FLTR-KIT-FC652", [
    CANON.OZONE_FILTER_1,
    CANON.OZONE_FILTER_2,
    CANON.VOC_FILTER,
    CANON.TONER_FILTER
])
ROL_KIT_FC75 = ROL_KIT_FC75
ROL_KIT_FC75_U = ROL_KIT_FC75_U
KIT_ROL_MR_4010 = KIT_ROL_MR_4010
DF_KIT_3031_FALLBACK = DF_KIT_3031_FALLBACK # RSDF
ASYS_ROLL_FEED_H373 = PmUnit("ASYS-ROLL-FEED-H373", [
    CANON.FEED_SFB
])
K_ROLL_PICK_BYP = K_ROLL_PICK_BYP
ROL_KIT_MP_2002 = ROL_KIT_MP_2002
ROL_KIT_MP2502_U_2 = PmUnit("ROL-KIT-MP2502-U", [
    CANON.FEED_O2LCF,
    CANON.PICK_O2LCF,
    CANON.SEP_O2LCF,
])

# 2018A / 2518A / 3018A / 3518A / 4518A / 5018A

DEV_KIT_5008A = PmUnit("DEV-KIT-5008A", [
    CANON.K_DEVELOPER,
    CANON.K_DRUM_BLADE,
    CANON.K_GRID,
    CANON.K_CLEANING_PAD,
    CANON.K_CHARGER_NEEDLE,
    CANON.SEPARATION_FINGER_DRUM,
    CANON.BELT_BLADE,
    CANON.TRANSFER_ROLLER
])
FR_KIT_3008A = PmUnit("FR-KIT-3008A", [
    CANON.OZONE_FILTER,
    CANON.FUSER_BELT,
    CANON.PRESS_ROLLER,
    CANON.SEPARATION_FINGER_FUSER,
])
FR_KIT_5008A = PmUnit("FR-KIT-5008A", [
    CANON.OZONE_FILTER,
    CANON.FUSER_BELT,
    CANON.PRESS_ROLLER,
    CANON.SEPARATION_FINGER_FUSER,
])
ROL_KIT_FC30_U = ROL_KIT_FC30_U
OD_4530 = PmUnit("OD-4530", [
    CANON.K_DRUM
])
# CR_3028TR = PmUnit("CR-3028TR", [
#     CANON.TRANSFER_ROLLER
# ])
ASYS_ROL_SPT_SFB_H373 = ASYS_ROL_SPT_SFB_H373
ASYS_ROL_SFB_H21X = ASYS_ROL_SFB_H21X
KIT_ROL_DSDF = KIT_ROL_DSDF
DF_KIT_3031_FALLBACK = DF_KIT_3031_FALLBACK # RSDF
ROL_KIT_1026 = ROL_KIT_1026

# 5518A / 5618A / 6518A / 6618A / 7518A / 7618A / 8518A / 8618A

EPU_KIT_FC556_G_K = EPU_KIT_FC556_G_K
EPU_KIT_FC556_S = EPU_KIT_FC556_S
FR_KIT_FC556_FU = FR_KIT_FC556_FU
TBU_KIT_FC556 = TBU_KIT_FC556
CR_FC556TR2 = CR_FC556TR2
OD_FC556 = OD_FC556
ROL_KIT_FC75 = ROL_KIT_FC75
ROL_KIT_FC75_U = ROL_KIT_FC75_U
KIT_ROL_DSDF = KIT_ROL_DSDF
K_RLR_FEED_SFB = K_RLR_FEED_SFB
K_ROLL_PICK_BYP = K_ROLL_PICK_BYP
ROL_KIT_MP2502_U = ROL_KIT_MP2502_U
FLTR_KIT_DP55 = PmUnit("FLTR-KIT-DP55", [
    CANON.OZONE_FILTER_1,
    CANON.OZONE_FILTER_2,
    CANON.VOC_FILTER,
    CANON.TONER_FILTER
])

# 2528A / 3028A / 3528A / 4528A

DEV_KIT_3028A = PmUnit("DEV-KIT-3028A", [
    CANON.K_DEVELOPER,
    CANON.K_DRUM_BLADE,
    CANON.K_GRID,
    CANON.K_CLEANING_PAD,
    CANON.K_CHARGER_NEEDLE,
    CANON.SEPARATION_FINGER_DRUM,
    CANON.TRANSFER_ROLLER,
    CANON.BELT_BLADE,
])
OD_3028 = PmUnit("OD-3028", [
    CANON.K_DRUM
]) 
FR_KIT_3008A = FR_KIT_3008A
FR_KIT_5008A = FR_KIT_5008A
ROL_KIT_FC30_U = ROL_KIT_FC30_U
ASYS_ROL_SFB_H21X = ASYS_ROL_SFB_H21X
ASYS_ROL_SPT_SFB_H373 = ASYS_ROL_SPT_SFB_H373
# CR_3028TR = CR_3028TR
ROL_KIT_KD_1073 = ROL_KIT_KD_1073
KIT_ROL_MR_4010 = KIT_ROL_MR_4010
DF_KIT_3031_FALLBACK = DF_KIT_3031_FALLBACK # RSDF
ROL_KIT_MP_2002 = ROL_KIT_MP_2002
FILTER_OZN_KCH_A08K_X2 = FILTER_OZN_KCH_A08K_X2

# 5528A / 6528A

DEV_KIT_FC425K = DEV_KIT_FC425K
TBU_KIT_FC50 = TBU_KIT_FC50
FR_KIT_FC6525 = FR_KIT_FC6525
ROL_KIT_FC30_U = ROL_KIT_FC30_U
OD_FC505 = OD_FC505
CR_FC30TR2 = CR_FC30TR2
ASYS_ROLL_SPT_H44X = PmUnit("ASYS-ROLL-SPT-H44X", [
    CANON.SEP_SFB
])
ASYS_ROLL_FEED_SFB_H44X = ASYS_ROLL_FEED_SFB_H44X
ROL_KIT_MP_2002 = ROL_KIT_MP_2002
ROL_KIT_KD_1073 = ROL_KIT_KD_1073
KIT_ROL_MR_4010 = KIT_ROL_MR_4010
DF_KIT_3031_FALLBACK = DF_KIT_3031_FALLBACK # RSDF
FILTER_OZN_KCH_A08K_X2 = FILTER_OZN_KCH_A08K_X2

# 6529A / 7529A / 9029A

EPU_KIT_FC556_G_K = EPU_KIT_FC556_G_K
EPU_KIT_FC556_S = EPU_KIT_FC556_S
FR_KIT_FC556_FU = FR_KIT_FC556_FU
TBU_KIT_FC556 = TBU_KIT_FC556
FLTR_KIT_DP55 = FLTR_KIT_DP55
ROL_KIT_FC75 = ROL_KIT_FC75
ROL_KIT_FC75_U = ROL_KIT_FC75_U
KIT_ROL_MR_4010 = KIT_ROL_MR_4010
DF_KIT_3031_FALLBACK = DF_KIT_3031_FALLBACK # RSDF
OD_FC556 = OD_FC556
CR_FC556TR2 = CR_FC556TR2
ASYS_ROLL_FEED_H373 = ASYS_ROLL_FEED_H373
K_ROLL_PICK_BYP = K_ROLL_PICK_BYP

# Catalogs

_330AC_400AC_clog = Catalog(
    [
        EPU_FC330_K,
        EPU_FC330_Y,
        EPU_FC330_M,
        EPU_FC330_C,
        TR_BLT_CLN_FC330_O,
        TR_BLT_FC330,
        TR_FC330_O,
        FUSER_FC330_120,
        ROLL_DR_FC330_O,
        ROLL_LR_FC330_O,
        ROLL_DF_FC330_O,
        ROLL_BR_FC330_O,
    ]
)

_2020AC_2520AC_clog = Catalog(
    [
        DEV_KIT_FC200CLR,
        DEV_KIT_FC200K,
        OD_FC30N,
        D_FC30_Y,
        D_FC30_M,
        D_FC30_C,
        D_FC30_K,
        CR_FC30TR2,
        ROL_KIT_FC30_U,
        ROL_KIT_KD_1073,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,
        ASYS_ROL_SFB_H21X,
        ASYS_ROL_SPT_SFB_H373,
    ]
)

_2515AC_3015AC_3515AC_clog = Catalog(
    [
        EPU_KIT_FC505CLR,
        DEV_KIT_FC505K,
        TBU_KIT_FC50,
        FR_KIT_FC505,
        OD_FC50,
        OD_FC505,
        D_FC505_Y,
        D_FC505_M,
        D_FC505_C,
        D_FC505_K,
        CR_FC30TR2,
        ROL_KIT_FC30_U,
        ROL_KIT_1026,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,        
        ASYS_ROL_SFB_H21X,
        ASYS_ROL_SPT_SFB_H373,
        FILTER_OZN_KCH_A08K,
    ]
)

_4515AC_5015AC_clog = Catalog(
    [
        EPU_KIT_FC505CLR,
        DEV_KIT_FC505K,
        TBU_KIT_FC50,
        FR_KIT_FC505H,
        OD_FC50,
        OD_FC505,
        D_FC505_Y,
        D_FC505_M,
        D_FC505_C,
        D_FC505_K,
        CR_FC30TR2,
        ROL_KIT_FC30_U,
        ROL_KIT_1026,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,
        ASYS_ROL_SFB_H21X,
        ASYS_ROL_SPT_SFB_H373,
        FILTER_OZN_KCH_A08K,
    ]
)

_5525AC_6525AC_clog = Catalog(
    [
        EPU_KIT_FC425CLR,
        DEV_KIT_FC425K,
        TBU_KIT_FC50,
        FR_KIT_FC6525,
        OD_FC50,
        OD_FC505,
        D_FC425_Y,
        D_FC425_M,
        D_FC425_C,
        D_FC425_K,
        FILTER_OZN_KCH_A08K_X2,
        CR_FC30TR2,
        ROL_KIT_FC30_U,
        ROL_KIT_MP_2002,
        ROL_KIT_KD_1073,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        ASYS_ROLL_FEED_SFB_H44X,
        ASYS_ROL_SPT_SFB_H373
    ]
)

_4525AC_clog = Catalog(
    [
        EPU_KIT_FC425CLR,
        DEV_KIT_FC425K,
        TBU_KIT_FC50,
        FR_KIT_FC505H,
        OD_FC50,
        OD_FC505,
        D_FC425_Y,
        D_FC425_M,
        D_FC425_C,
        D_FC425_K,
        FILTER_OZN_KCH_A08K_X2,
        CR_FC30TR2,
        ROL_KIT_FC30_U,
        ROL_KIT_MP_2002,
        ROL_KIT_KD_1073,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        ASYS_ROLL_FEED_SFB_H44X,
        ASYS_ROL_SPT_SFB_H373
    ]
)

_2525AC_3025AC_3525AC_clog = Catalog(
    [
        EPU_KIT_FC425CLR,
        DEV_KIT_FC425K,
        TBU_KIT_FC50,
        FR_KIT_FC3525,
        OD_FC50,
        OD_FC505,
        D_FC425_Y,
        D_FC425_M,
        D_FC425_C,
        D_FC425_K,
        FILTER_OZN_KCH_A08K_X2,
        CR_FC30TR2,
        ROL_KIT_FC30_U,
        ROL_KIT_MP_2002,
        ROL_KIT_KD_1073,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        ASYS_ROLL_FEED_SFB_H44X,
        ASYS_ROL_SPT_SFB_H373
    ]
)

_5516AC_5616AC_6516AC_6616AC_clog = Catalog(
    [
        FR_KIT_FC556_FU,
        EPU_KIT_FC556_G_Y,
        EPU_KIT_FC556_G_M,
        EPU_KIT_FC556_G_C,
        EPU_KIT_FC556_G_K,
        OD_FC556,
        CR_FC556TR2,
        TBU_KIT_FC556,
        FLTR_KIT_FC556,
        ROL_KIT_FC75,
        ROL_KIT_FC75_U,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,
        ROL_KIT_MP2502_U,
        K_RLR_FEED_SFB,
        K_ROLL_PICK_BYP
    ]
)

_7516AC_7616AC_clog = Catalog(
    [
        FR_KIT_FC556_FU,
        EPU_KIT_FC556_G_Y,
        EPU_KIT_FC556_G_M,
        EPU_KIT_FC556_G_C,
        EPU_KIT_FC556_S,
        OD_FC556,
        CR_FC556TR2,
        TBU_KIT_FC556,
        FLTR_KIT_FC556,
        ROL_KIT_FC75,
        ROL_KIT_FC75_U,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,
        ROL_KIT_MP2502_U,
        K_RLR_FEED_SFB,
        K_ROLL_PICK_BYP
    ]
)

_6526AC_6527AC_clog = Catalog(
    [
        FR_KIT_FC556_FU,
        EPU_KIT_FC556_G_C,
        EPU_KIT_FC556_G_Y,
        EPU_KIT_FC556_G_M,
        EPU_KIT_FC556_G_K,
        OD_FC556,
        TBU_KIT_FC556,
        CR_FC556TR2,
        FLTR_KIT_FC652,
        ROL_KIT_FC75,
        ROL_KIT_FC75_U,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        ASYS_ROLL_FEED_H373,
        K_ROLL_PICK_BYP,
        ROL_KIT_MP_2002,
        ROL_KIT_MP2502_U_2,
    ]
)

_7527AC_clog = Catalog(
    [
        FR_KIT_FC556_FU,
        EPU_KIT_FC556_G_C,
        EPU_KIT_FC556_G_Y,
        EPU_KIT_FC556_G_M,
        EPU_KIT_FC556_S,
        OD_FC556,
        TBU_KIT_FC556,
        CR_FC556TR2,
        FLTR_KIT_FC652,
        ROL_KIT_FC75,
        ROL_KIT_FC75_U,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        ASYS_ROLL_FEED_H373,
        K_ROLL_PICK_BYP,
        ROL_KIT_MP_2002,
        ROL_KIT_MP2502_U_2,
    ]
)

_2018A_2518A_3018A_clog = Catalog(
    [
        DEV_KIT_5008A,
        FR_KIT_3008A,
        ROL_KIT_FC30_U,
        OD_4530,
        # CR_3028TR,
        ASYS_ROL_SPT_SFB_H373,
        ASYS_ROL_SFB_H21X,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,
        ROL_KIT_1026,
    ]
)

_3518A_4518A_5018A_clog = Catalog(
    [
        DEV_KIT_5008A,
        FR_KIT_5008A,
        ROL_KIT_FC30_U,
        # CR_3028TR,
        OD_4530,
        ASYS_ROL_SPT_SFB_H373,
        ASYS_ROL_SFB_H21X,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,
        ROL_KIT_1026
    ]
)

_5518A_5618A_6518A_6618A_7518A_7618A_clog = Catalog(
    [
        EPU_KIT_FC556_G_K,
        FR_KIT_FC556_FU,
        TBU_KIT_FC556,
        CR_FC556TR2,
        OD_FC556,
        ROL_KIT_FC75,
        ROL_KIT_FC75_U,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,
        K_RLR_FEED_SFB,
        K_ROLL_PICK_BYP,
        ROL_KIT_MP2502_U,
        FLTR_KIT_DP55,
    ]
)

_8518A_8618A_clog = Catalog(
    [
        EPU_KIT_FC556_S,
        FR_KIT_FC556_FU,
        TBU_KIT_FC556,
        CR_FC556TR2,
        OD_FC556,
        ROL_KIT_FC75,
        ROL_KIT_FC75_U,
        KIT_ROL_DSDF,
        DF_KIT_3031_FALLBACK,
        K_RLR_FEED_SFB,
        K_ROLL_PICK_BYP,
        ROL_KIT_MP2502_U,
        FLTR_KIT_DP55,
    ]
)

_2528A_3028A_clog = Catalog(
    [
        DEV_KIT_3028A,
        OD_3028,
        FR_KIT_3008A,
        ROL_KIT_FC30_U,
        ASYS_ROL_SFB_H21X,
        ASYS_ROL_SPT_SFB_H373,
        # CR_3028TR,
        ROL_KIT_KD_1073,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        ROL_KIT_MP_2002
    ]
) 

_3528A_4528A_clog = Catalog(
    [
        DEV_KIT_3028A,
        OD_3028,
        FR_KIT_5008A,
        ROL_KIT_FC30_U,
        ASYS_ROL_SFB_H21X,
        ASYS_ROL_SPT_SFB_H373,
        # CR_3028TR,
        ROL_KIT_KD_1073,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        ROL_KIT_MP_2002
    ]
)

_5528A_6528A_clog = Catalog(
    [
        DEV_KIT_FC425K,
        TBU_KIT_FC50,
        FR_KIT_FC6525,
        ROL_KIT_FC30_U,
        OD_FC505,
        CR_FC30TR2,
        ASYS_ROLL_SPT_H44X,
        ASYS_ROLL_FEED_SFB_H44X,
        ROL_KIT_MP_2002,
        ROL_KIT_KD_1073,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        FILTER_OZN_KCH_A08K_X2,
    ]
)

_6529A_7529A_clog = Catalog(
    [
        EPU_KIT_FC556_G_K,
        FR_KIT_FC556_FU,
        TBU_KIT_FC556,
        FLTR_KIT_DP55,
        ROL_KIT_FC75,
        ROL_KIT_FC75_U,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        OD_FC556,
        CR_FC556TR2,
        ASYS_ROLL_FEED_H373,
        K_ROLL_PICK_BYP,
    ]
)

_9029A_clog = Catalog(
    [
        EPU_KIT_FC556_S,
        FR_KIT_FC556_FU,
        TBU_KIT_FC556,
        FLTR_KIT_DP55,
        ROL_KIT_FC75,
        ROL_KIT_FC75_U,
        KIT_ROL_MR_4010,
        DF_KIT_3031_FALLBACK,
        OD_FC556,
        CR_FC556TR2,
        ASYS_ROLL_FEED_H373,
        K_ROLL_PICK_BYP,
    ]
)

# All Supported Models
_330AC = Model(_330AC_400AC_clog)
_400AC = Model(_330AC_400AC_clog)

_2020AC = Model(_2020AC_2520AC_clog)
_2520AC = Model(_2020AC_2520AC_clog)

_2515AC = Model(_2515AC_3015AC_3515AC_clog)
_3015AC = Model(_2515AC_3015AC_3515AC_clog)
_3515AC = Model(_2515AC_3015AC_3515AC_clog)
_4515AC = Model(_4515AC_5015AC_clog)
_5015AC = Model(_4515AC_5015AC_clog)

_2525AC = Model(_2525AC_3025AC_3525AC_clog)
_3025AC = Model(_2525AC_3025AC_3525AC_clog)
_3525AC = Model(_2525AC_3025AC_3525AC_clog)
_4525AC = Model(_4525AC_clog)
_5525AC = Model(_5525AC_6525AC_clog)
_6525AC = Model(_5525AC_6525AC_clog)

_5516AC = Model(_5516AC_5616AC_6516AC_6616AC_clog)
_5616AC = Model(_5516AC_5616AC_6516AC_6616AC_clog)
_6516AC = Model(_5516AC_5616AC_6516AC_6616AC_clog)
_6616AC = Model(_5516AC_5616AC_6516AC_6616AC_clog)
_7516AC = Model(_7516AC_7616AC_clog)
_7616AC = Model(_7516AC_7616AC_clog)

_6526AC = Model(_6526AC_6527AC_clog)
_6527AC = Model(_6526AC_6527AC_clog)
_7527AC = Model(_7527AC_clog)

_2018A = Model(_2018A_2518A_3018A_clog)
_2518A = Model(_2018A_2518A_3018A_clog)
_3018A = Model(_2018A_2518A_3018A_clog)
_3518A = Model(_3518A_4518A_5018A_clog)
_4518A = Model(_3518A_4518A_5018A_clog)
_5018A = Model(_3518A_4518A_5018A_clog)

_5518A = Model(_5518A_5618A_6518A_6618A_7518A_7618A_clog)
_5618A = Model(_5518A_5618A_6518A_6618A_7518A_7618A_clog)
_6518A = Model(_5518A_5618A_6518A_6618A_7518A_7618A_clog)
_6618A = Model(_5518A_5618A_6518A_6618A_7518A_7618A_clog)
_7518A = Model(_5518A_5618A_6518A_6618A_7518A_7618A_clog)
_7618A = Model(_5518A_5618A_6518A_6618A_7518A_7618A_clog)
_8518A = Model(_8518A_8618A_clog)
_8618A = Model(_8518A_8618A_clog)

_2528A = Model(_2528A_3028A_clog)
_3028A = Model(_2528A_3028A_clog)
_3528A = Model(_3528A_4528A_clog)
_4528A = Model(_3528A_4528A_clog)

_5528A = Model(_5528A_6528A_clog)
_6528A = Model(_5528A_6528A_clog)

_6529A = Model(_6529A_7529A_clog)
_7529A = Model(_6529A_7529A_clog)
_9029A = Model(_9029A_clog)

REGISTRY = {
    "330AC": _330AC,
    "400AC": _400AC,

    "2020AC": _2020AC,
    "2520AC": _2520AC,

    "2515AC": _2515AC,
    "3015AC": _3015AC,
    "3515AC": _3515AC,
    "4515AC": _4515AC,
    "5015AC": _5015AC,

    "2525AC": _2525AC,
    "3025AC": _3025AC,
    "3525AC": _3525AC,
    "4525AC": _4525AC,
    "5525AC": _5525AC,
    "6525AC": _6525AC,

    "5516AC": _5516AC,
    "5616AC": _5616AC,
    "6516AC": _6516AC,
    "6616AC": _6616AC,
    "7516AC": _7516AC,
    "7616AC": _7616AC,

    "6526AC": _6526AC,
    "6527AC": _6527AC,
    "7527AC": _7527AC,

    "2018A": _2018A,
    "2518A": _2518A,
    "3018A": _3018A,
    "3518A": _3518A,
    "4518A": _4518A,
    "5018A": _5018A,
    
    "5518A": _5518A,
    "5618A": _5618A,
    "6618A": _6618A,
    "6518A": _6518A,
    "7518A": _7518A,
    "7618A": _7618A,
    "8518A": _8518A,
    "8618A": _8618A,

    "2528A": _2528A,
    "3028A": _3028A,
    "3528A": _3528A,
    "4528A": _4528A,
    
    "5528A": _5528A,
    "6528A": _6528A,

    "6529A": _6529A,
    "7529A": _7529A,
    "9029A": _9029A,
}

DB_PATH = "catalog_manager.db"

def init_db(cursor):
    # 1. Regex Mappings
    cursor.execute("""CREATE TABLE IF NOT EXISTS canon_mappings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern TEXT UNIQUE,
        template TEXT
    )""")
    
    # 2. Kits (PmUnits)
    cursor.execute("""CREATE TABLE IF NOT EXISTS pm_units (
        unit_name TEXT PRIMARY KEY
    )""")
    
    # 3. Items inside Kits
    cursor.execute("""CREATE TABLE IF NOT EXISTS unit_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_name TEXT,
        canon_item TEXT,
        FOREIGN KEY(unit_name) REFERENCES pm_units(unit_name)
    )""")
    
    # 4. Models and their Catalogs
    cursor.execute("""CREATE TABLE IF NOT EXISTS models (
        model_name TEXT PRIMARY KEY
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS model_catalog (
        model_name TEXT,
        unit_name TEXT,
        PRIMARY KEY(model_name, unit_name),
        FOREIGN KEY(model_name) REFERENCES models(model_name),
        FOREIGN KEY(unit_name) REFERENCES pm_units(unit_name)
    )""")

    # 5. Quantity Overrides
    cursor.execute("""CREATE TABLE IF NOT EXISTS qty_overrides (
        unit_name TEXT PRIMARY KEY,
        quantity INTEGER NOT NULL,
        FOREIGN KEY(unit_name) REFERENCES pm_units(unit_name)
    )""")

    # 6. Unit semantics (count once per color channel)
    cursor.execute("""CREATE TABLE IF NOT EXISTS per_color_units (
        unit_name TEXT PRIMARY KEY,
        FOREIGN KEY(unit_name) REFERENCES pm_units(unit_name)
    )""")

def migrate_data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    init_db(cur)
    
    # --- Migrate Canon Mappings ---
    for pattern_obj, template in CANON_MAP.items():
        cur.execute("INSERT OR IGNORE INTO canon_mappings (pattern, template) VALUES (?, ?)", 
                    (pattern_obj.pattern, template))
    
    # --- Migrate Models and Kits ---
    for model_name, model_obj in REGISTRY.items():
        cur.execute("INSERT OR IGNORE INTO models (model_name) VALUES (?)", (model_name,))
        
        catalog = getattr(model_obj, "catalog", None)
        if catalog and hasattr(catalog, "pm_units"):
            for unit in catalog.pm_units:
                cur.execute("INSERT OR IGNORE INTO pm_units (unit_name) VALUES (?)", (unit.unit_name,))
                
                for item in unit.canon_items:
                    cur.execute("SELECT 1 FROM unit_items WHERE unit_name=? AND canon_item=?", (unit.unit_name, item))
                    if not cur.fetchone():
                        cur.execute("INSERT INTO unit_items (unit_name, canon_item) VALUES (?, ?)", 
                                    (unit.unit_name, item))
                
                cur.execute("INSERT OR IGNORE INTO model_catalog (model_name, unit_name) VALUES (?, ?)", 
                            (model_name, unit.unit_name))

    # --- Seed Quantity Overrides ---
    qty_overrides = [
        (FILTER_OZN_KCH_A08K.unit_name, 2),
        (ASYS_ROLL_FEED_SFB_H44X.unit_name, 2),
    ]
    for unit_name, qty in qty_overrides:
        cur.execute(
            "INSERT OR IGNORE INTO qty_overrides (unit_name, quantity) VALUES (?, ?)",
            (unit_name, qty),
        )

    # --- Seed Per-Color Unit Semantics ---
    # ─────────────────────────────────────────────────────────────────────────────
    # All PmUnit names listed here are treated as *per-color kits* by the rules engine.
    # That means each kit will count **once per color channel (K/C/M/Y)**, regardless
    # of how many color-tagged canons inside it are due (e.g., DRUM[K], GRID[K], etc.).
    # 
    # This prevents double-counting within multi-part developer/drum units such as
    # EPU-FC330-K or EPU-KIT-FC556-G, which include several related K-channel canons.
    # ─────────────────────────────────────────────────────────────────────────────
    per_color_units = [
        EPU_KIT_FC556_G_K.unit_name, # Even though this doesnt include CMY, they are the same unit name so they do not need to be included
        EPU_FC330_K.unit_name,
        EPU_FC330_Y.unit_name,
        EPU_FC330_M.unit_name,
        EPU_FC330_C.unit_name,
    ]
    for unit_name in per_color_units:
        cur.execute(
            "INSERT OR IGNORE INTO per_color_units (unit_name) VALUES (?)",
            (unit_name,),
        )
    
    conn.commit()
    print(f"Migration complete! Data saved to {DB_PATH}")
    conn.close()

if __name__ == "__main__":
   migrate_data()