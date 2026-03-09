import sys

from lxml import etree

from .parser import encode_4gl, parse_xml


def main() -> None:
    # Simple placeholder: parse XML, encode to 4GL print
    
    # Check we have enough args
    if len(sys.argv) < 2:
        print("Usage:\n    uv run gorak <xml_file>")
        sys.exit(1)
    
    xml_path = sys.argv[1]
    xml = etree.parse(xml_path)
    component = parse_xml(xml)
    print(encode_4gl(component))

if __name__ == "__main__":
    main()