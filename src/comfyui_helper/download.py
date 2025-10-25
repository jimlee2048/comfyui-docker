import subprocess
import time
import aria2p

from .utils import logger


class Downloader:
    def __init__(self):
        self.aria2 = self._launch_aria2c()

    def _check_aria2c(
        self,
        aria2: aria2p.API,
        max_retries: int = 3,
        retries_interval: int = 2,
    ):
        if not isinstance(aria2, aria2p.API):
            return False
        for _ in range(max_retries):
            try:
                aria2.get_stats()
                return True
            except Exception:
                time.sleep(retries_interval)
        return False

    def _launch_aria2c(self, port: int = 6800):
        aria2 = aria2p.API(aria2p.Client(host="http://localhost", port=port, secret=""))
        # check if aria2c is already running
        if self._check_aria2c(aria2, max_retries=0):
            logger.info("✅ aria2c is already running")
            return aria2
        # if not, try to launch aria2c
        logger.info("🚀 Launching aria2c...")
        try:
            subprocess.run(
                [
                    "aria2c",
                    "--daemon=true",
                    "--enable-rpc",
                    f"--rpc-listen-port={port}",
                    "--max-concurrent-downloads=1",
                    "--max-connection-per-server=16",
                    "--split=16",
                    "--continue=true",
                    "--disable-ipv6=true",
                ],
                check=True,
            )
            # sleep a while to ensure aria2c is ready
            time.sleep(2)
            # check if aria2c is ready
            if not self._check_aria2c(aria2):
                raise RuntimeError("Failed to connect to aria2c after launching.")
            # purge all completed, removed or failed downloads from the queue
            aria2.purge()
            return aria2
        except Exception as e:
            logger.error(f"❌ Failed to launch aria2c: {str(e)}")
            raise e

    def download(
        self,
        url: str,
        filename: str,
        dir: str,
        header: str = None,
        max_retries: int = 3,
        retries_interval: int = 2,
    ) -> bool:
        download_options = {"dir": dir, "out": filename}
        if header:
            download_options["header"] = header

        for attempt in range(max_retries):
            try:
                download = self.aria2.add_uris([url], download_options)
                # print download progress
                while not download.is_complete:
                    download.update()
                    if download.status == "error":
                        download.remove(files=True)
                        raise Exception(f"{download.error_message}")
                    if download.status == "removed":
                        raise Exception("Download was removed")
                    logger.info(
                        f"{filename}: {download.progress_string()} | {download.completed_length_string()}/{download.total_length_string()} [{download.eta_string()}, {download.download_speed_string()}]"
                    )
                    time.sleep(1)
                logger.info(f"✅ Downloaded: {filename} -> {dir}")
                return True
            except Exception as e:
                e_msg = str(e)
                logger.error(f"❌ Failed to download {filename}: {e_msg}")
                # if authorization failed, abort
                if "authorization failed" in e_msg.lower():
                    logger.warning(
                        "⚠️ Please check your token in environment variables."
                    )
                    return False
                # if max retries reached, abort
                elif attempt == max_retries - 1:
                    break
                # retry
                else:
                    logger.warning(
                        f"⚠️ Retrying in {retries_interval} seconds... ({attempt + 1}/{max_retries})"
                    )
                    time.sleep(retries_interval)
        logger.error("❌ Max retries reached, abort.")
        return False
