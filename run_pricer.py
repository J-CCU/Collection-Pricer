"""Start the collection pricer (also the PyInstaller entry point)."""
import multiprocessing as mp

from cardpricer.app import App

if __name__ == "__main__":
    mp.freeze_support()
    App().mainloop()
