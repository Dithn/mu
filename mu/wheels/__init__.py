#
# Download wheels corresponding to the baseline modes
#
import os
import sys
import glob
import logging
import platform
import subprocess
import tempfile
import zipfile

from .. import __version__ as mu_version


class WheelsError(Exception):
    def __init__(self, message):
        self.message = message


class WheelsDownloadError(WheelsError):
    pass


class WheelsBuildError(WheelsError):
    pass


logger = logging.getLogger(__name__)

WHEELS_DIRPATH = os.path.dirname(__file__)
ZIP_FILEPATH = os.path.join(WHEELS_DIRPATH, mu_version + ".zip")

#
# List of base packages to support modes
# The first element should be the importable name (so "serial" rather than "pyserial")
# The second element is passed to `pip download|install`
# Any additional elements are passed to `pip` for specific purposes
#
mode_packages = [
    ("pgzero", "pgzero>=1.2.1"),
    ("flask", "flask==1.1.2"),
    # The version of ipykernel here should match to the version used by
    # qtconsole at the version specified in setup.py
    # FIXME: ipykernel max ver added for macOS 10.13 compatibility, min taken
    # from qtconsole 4.7.7. This is mirrored in setup.py
    ("ipykernel", "ipykernel>=4.1,<6"),
    ("esptool", "esptool==3.*"),
]

# TODO: Temp app signing workaround https://github.com/mu-editor/mu/issues/1290
if sys.version_info[:2] == (3, 8) and platform.system() == "Darwin":
    mode_packages = [
        (
            "pygame",
            "https://github.com/mu-editor/pygame/releases/download/2.0.1/"
            "pygame-2.0.1-cp38-cp38-macosx_10_9_intel.whl",
        ),
        ("numpy", "numpy==1.20.1"),
        (
            "pgzero",
            "https://github.com/mu-editor/pgzero/releases/download/mu-wheel/"
            "pgzero-1.2-py3-none-any.whl",
            "--no-index",
        ),
    ] + mode_packages[1:]


def compact(text):
    """Remove double line spaces and anything else which might help"""
    return "\n".join(line for line in text.splitlines() if line.strip())


def remove_dist_files(dirpath, logger):
    #
    # Clear the directory of any existing wheels and source distributions
    # (this is especially important because there may have been wheels
    # left over from a test with a different Python version)
    #
    logger.info("Removing wheel/sdist files from %s", dirpath)
    rm_files = (
        glob.glob(os.path.join(dirpath, "*.whl"))
        + glob.glob(os.path.join(dirpath, "*.gz"))
        + glob.glob(os.path.join(dirpath, "*.zip"))
    )
    for rm_filepath in rm_files:
        logger.debug("Removing existing wheel/sdist %s", rm_filepath)
        os.remove(rm_filepath)


def pip_download(dirpath, logger):
    for name, pip_identifier, *extra_flags in mode_packages:
        logger.info(
            "Running pip download for %s / %s / %s",
            name,
            pip_identifier,
            extra_flags,
        )
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "--disable-pip-version-check",
                "download",
                "--destination-directory",
                dirpath,
                "--find-links",
                dirpath,
                pip_identifier,
            ]
            + extra_flags,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        logger.debug(compact(process.stdout.decode("utf-8")))

        #
        # If any wheel fails to download, remove any files already downloaded
        # (to ensure the download is triggered again) and raise an exception
        # NB Probably not necessary now that we're using a temp directory
        #
        if process.returncode != 0:
            raise WheelsDownloadError(
                "Pip was unable to download %s" % pip_identifier
            )


def convert_sdists_to_wheels(dirpath, logger):
    #
    # Convert any sdists to wheels
    #
    for filepath in glob.glob(os.path.join(dirpath, "*")):
        if filepath.endswith(("gz", ".zip")):
            logger.info("Building wheel for %s", filepath)
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--wheel-dir",
                    dirpath,
                    filepath,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            logger.debug(compact(process.stdout.decode("utf-8")))
            if process.returncode != 0:
                logger.warning("Unable to build a wheel for %s", filepath)
            else:
                os.remove(filepath)


def zip_wheels(zip_filepath, dirpath, logger=logger):
    """Zip all the wheels into an archive"""
    logger.info("Building zip %s from wheels in %s", zip_filepath, dirpath)
    with zipfile.ZipFile(zip_filepath, "w") as z:
        for filepath in glob.glob(os.path.join(dirpath, "*.whl")):
            filename = os.path.basename(filepath)
            logger.debug("Adding %s to zip", filename)
            z.write(filepath, filename)


def download(zip_filepath=ZIP_FILEPATH, logger=logger):
    """Download from PyPI, convert to wheels, and zip up

    To make all the libraries available for Mu modes (eg pygame zero, Flask etc.)
    we `pip download` them to a temporary location and then pack them into a
    zip file which is tagged with the current Mu version number

    We allow `logger` to be overridden because output from the
    virtual_environment module logger goes to the splash screen, while
    output from this module's logger doesn't
    """
    logger.info("Downloading wheels to %s", zip_filepath)

    #
    # Remove any leftover files from the place where the zip file
    # will be -- usually the `wheels` package folder
    #
    remove_dist_files(os.path.dirname(zip_filepath), logger)

    with tempfile.TemporaryDirectory() as temp_dirpath:
        pip_download(temp_dirpath, logger)
        convert_sdists_to_wheels(temp_dirpath, logger)
        zip_wheels(zip_filepath, temp_dirpath, logger)
