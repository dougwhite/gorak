from .domain import Application, ComponentInfo


def table_rows(output: str, expected_cells: int, header: str) -> list[list[str]]:
    """Extract data rows from Ingres terminal monitor boxed table output."""

    rows: list[list[str]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
        if len(cells) == expected_cells and cells[0] != header:
            rows.append(cells)

    return rows


def parse_app_list_output(output: str) -> list[Application]:
    """Parse Ingres terminal monitor output into application metadata."""

    return [
        Application(
            name=cells[0],
            start_component=cells[1],
            description=cells[2],
        )
        for cells in table_rows(output, expected_cells=3, header="application_name")
    ]


def parse_component_list_output(output: str) -> list[ComponentInfo]:
    """Parse Ingres terminal monitor output into component metadata."""

    return [
        ComponentInfo(
            application_name=cells[0],
            name=cells[1],
            type=cells[2],
            description=cells[3],
        )
        for cells in table_rows(output, expected_cells=4, header="application_name")
    ]
