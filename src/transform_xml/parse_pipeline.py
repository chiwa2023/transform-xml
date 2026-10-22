"""Alias module for analyze_pipeline."""

from transform_xml.analyze_pipeline import (
    main,
    resolve_target_directory,
    run_analyze_pipeline,
)

if __name__ == "__main__":
    import sys

    sys.exit(main())
