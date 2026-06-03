from pmgen.io import fetch_serials, http_client


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.pages[url])


def _device_row(serial: str, customer: str) -> str:
    return (
        "<tr>"
        f'<td class="deviceSerialNumbers">{serial}</td>'
        f'<td class="deviceCustomers">{customer}</td>'
        "</tr>"
    )


def _generic_device_table(serial: str, customer: str) -> str:
    return (
        "<table>"
        "<tr><th>Serial Number</th><th>Customer Name</th></tr>"
        f"<tr><td>{serial}</td><td>{customer}</td></tr>"
        "</table>"
    )


def _inactive_unassigned_device_row(serial: str) -> str:
    return (
        "<table><tr>"
        "<td style='display:none;' id='Device_1693467'>1</td>"
        "<td style='white-space:nowrap'>"
        f"<a id='inactive_1693467' onclick='getDeviceInfo(1693467); return false;'> {serial} </a>"
        "</td>"
        "<td class='break-word deviceMachineID'>IN5913DTP</td>"
        "<td class='deviceModels break-word'>ESTUDIO6527ACT</td>"
        "<td class='break-word'>"
        "<span style='font-style:italic; color:Gray' class='noCustomerName'>(No Customer Assigned)</span>"
        "<a href='#' class='deviceCustomers' onclick=\"getCustomerInfoView('1693467'); return false;\">Edit</a>"
        "</td>"
        "<td class='status'>Deactivated</td>"
        "</tr></table>"
    )


def test_get_inactive_serials_fetches_inactive_page_and_parses_serials():
    session = FakeSession({
        fetch_serials.DEVICE_INDEX_INACTIVE: '<div data-serial="INAC67890"></div>'
    })

    serials = fetch_serials.get_inactive_serials(session)

    assert serials == ["INAC67890"]
    assert session.calls[0][0] == fetch_serials.DEVICE_INDEX_INACTIVE
    assert session.calls[0][1]["allow_redirects"] is True


def test_get_serials_after_login_includes_active_and_inactive_serials():
    session = FakeSession({
        http_client.DEVICE_INDEX: (
            '<div data-serial="ACTV12345"></div>'
            '<a href="/Device/Details?serial=DUPL11111">details</a>'
        ),
        http_client.DEVICE_INDEX_INACTIVE: (
            '<div data-serial="INAC67890"></div>'
            '<div data-serial="ACTV12345"></div>'
        ),
    })

    serials = http_client.get_serials_after_login(session)

    assert serials == ["ACTV12345", "DUPL11111", "INAC67890"]
    assert [call[0] for call in session.calls] == [
        http_client.DEVICE_INDEX,
        http_client.DEVICE_INDEX_INACTIVE,
    ]


def test_get_serial_status_map_after_login_marks_active_and_inactive_serials():
    session = FakeSession({
        http_client.DEVICE_INDEX: (
            '<div data-serial="ACTV12345"></div>'
            '<div data-serial="DUPL11111"></div>'
        ),
        http_client.DEVICE_INDEX_INACTIVE: (
            '<div data-serial="INAC67890"></div>'
            '<div data-serial="DUPL11111"></div>'
        ),
    })

    serial_status_map = http_client.get_serial_status_map_after_login(session)

    assert serial_status_map == {
        "ACTV12345": "Active",
        "DUPL11111": "Active",
        "INAC67890": "Inactive",
    }


def test_get_customer_map_after_login_includes_inactive_customers():
    session = FakeSession({
        http_client.DEVICE_INDEX: (
            "<table>"
            + _device_row("ACTV12345", "Active Customer")
            + _device_row("DUPL11111", "Active Duplicate")
            + "</table>"
        ),
        http_client.DEVICE_INDEX_INACTIVE: (
            "<table>"
            + _device_row("INAC67890", "Inactive Customer")
            + _device_row("DUPL11111", "Inactive Duplicate")
            + "</table>"
        ),
    })

    customer_map = http_client.get_customer_map_after_login(session)

    assert customer_map == {
        "ACTV12345": "Active Customer",
        "DUPL11111": "Active Duplicate",
        "INAC67890": "Inactive Customer",
    }


def test_get_customer_map_after_login_parses_inactive_customer_header_table():
    session = FakeSession({
        http_client.DEVICE_INDEX: "<table></table>",
        http_client.DEVICE_INDEX_INACTIVE: _generic_device_table("inac67890", "Inactive Customer"),
    })

    customer_map = http_client.get_customer_map_after_login(session)

    assert customer_map == {"INAC67890": "Inactive Customer"}


def test_get_customer_map_after_login_uses_unassigned_customer_placeholder():
    session = FakeSession({
        http_client.DEVICE_INDEX: "<table></table>",
        http_client.DEVICE_INDEX_INACTIVE: _inactive_unassigned_device_row("S6CQ85276"),
    })

    customer_map = http_client.get_customer_map_after_login(session)

    assert customer_map == {"S6CQ85276": "(No Customer Assigned)"}