# This file is part of ranger, the console file manager.
# License: GNU GPL version 3, see the file "AUTHORS" for details.

from __future__ import absolute_import, division, print_function

import os
import sys
import mmap
from subprocess import check_call, CalledProcessError
from collections import namedtuple

from tempfile import TemporaryFile

from ranger import PY3
from ranger.core.shared import FileManagerAware
from ranger.ext.popen23 import DEVNULL
from ranger.ext.which import which

from .displayer import (
    register_image_displayer,
    ImageDisplayer,
    ImageDisplayError,
    get_font_dimensions,
    temporarily_moved_cursor,
)

if which("magick"):
    # Magick >= 7
    MAGICK_CONVERT_CMD_BASE = ("magick",)
else:
    # Magick < 7
    MAGICK_CONVERT_CMD_BASE = ("convert",)

_CacheableSixelImage = namedtuple("_CacheableSixelImage", ("width", "height", "inode"))

_CachedSixelImage = namedtuple("_CachedSixelImage", ("image", "fh"))


@register_image_displayer("sixel")
class SixelImageDisplayer(ImageDisplayer, FileManagerAware):
    """Implementation of ImageDisplayer using SIXEL."""

    def __init__(self):
        self.win = None
        self.cache = {}
        self.fm.signal_bind('preview.cleared', lambda signal: self._clear_cache(signal.path))

    def _clear_cache(self, path):
        if os.path.exists(path):
            self.cache = {
                ce: cd
                for ce, cd in self.cache.items()
                if ce.inode != os.stat(path).st_ino
            }

    def _sixel_cache(self, path, width, height):
        stat = os.stat(path)
        cacheable = _CacheableSixelImage(width, height, stat.st_ino)

        if cacheable not in self.cache:
            font_width, font_height = get_font_dimensions()
            fit_width = font_width * width
            fit_height = font_height * height

            sixel_dithering = self.fm.settings.sixel_dithering
            cached = TemporaryFile("w+", prefix="ranger", suffix=path.replace(os.sep, "-"))

            environ = dict(os.environ)
            environ.setdefault("MAGICK_OCL_DEVICE", "true")
            try:
                check_call(
                    [
                        *MAGICK_CONVERT_CMD_BASE,
                        path + "[0]",
                        "-geometry",
                        "{0}x{1}>".format(fit_width, fit_height),
                        "-dither",
                        sixel_dithering,
                        "sixel:-",
                    ],
                    stdout=cached,
                    stderr=DEVNULL,
                    env=environ,
                )
            except CalledProcessError:
                raise ImageDisplayError("ImageMagick failed processing the SIXEL image")
            except FileNotFoundError:
                raise ImageDisplayError("SIXEL image previews require ImageMagick")
            finally:
                cached.flush()

            if os.fstat(cached.fileno()).st_size == 0:
                raise ImageDisplayError("ImageMagick produced an empty SIXEL image file")

            self.cache[cacheable] = _CachedSixelImage(mmap.mmap(cached.fileno(), 0), cached)

        return self.cache[cacheable].image

    # pylint: disable=too-many-positional-arguments
    def draw(self, path, start_x, start_y, width, height):
        if self.win is None:
            self.win = self.fm.ui.win.subwin(height, width, start_y, start_x)
        else:
            self.win.mvwin(start_y, start_x)
            self.win.resize(height, width)

        with temporarily_moved_cursor(start_y, start_x):
            sixel = self._sixel_cache(path, width, height)[:]
            if PY3:
                sys.stdout.buffer.write(sixel)
            else:
                sys.stdout.write(sixel)
            sys.stdout.flush()

    def clear(self, start_x, start_y, width, height):
        if self.win is not None:
            self.win.clear()
            self.win.refresh()

            self.win = None

        self.fm.ui.win.redrawwin()

    def quit(self):
        self.clear(0, 0, 0, 0)
        self.cache = {}
