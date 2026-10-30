import sys
import multiprocessing

from ymtools.src.cli_entry import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
