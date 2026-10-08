"""Main module for transform_xml."""

import sys


def hello_world(name: str = "World") -> str:
    """Return a hello world greeting message."""
    return f"Hello, {name}!"


def main() -> None:
    """CLI entry point for transform_xml."""
    message = hello_world()
    print(message)


if __name__ == "__main__":
    main()
