# This file is part of ranger, the console file manager.
# License: GNU GPL version 3, see the file "AUTHORS" for details.
# Author: Emanuel Guevel, 2013
# Author: Delisa Mason, 2015

"""Interface for drawing images into the console

This module provides functions to draw images in the terminal using supported
implementations.
"""
from __future__ import (absolute_import, division, print_function)

from .displayer import (
    get_image_displayer,
    ImageDisplayer,
    ImageDisplayError,
    ImgDisplayUnsupportedException,
    register_image_displayer,
)

from . import kitty, urxvt, terminology, sixel, iterm, w3m  # noqa: F401

__all__ = [
    "get_image_displayer",
    "ImageDisplayer",
    "ImageDisplayError",
    "ImgDisplayUnsupportedException",
]

import os
import json
import threading
from subprocess import Popen, PIPE 

from ranger.ext.which import which


if which("magick"):
    # Magick >= 7
    MAGICK_CONVERT_CMD_BASE = ("magick",)
else:
    # Magick < 7
    MAGICK_CONVERT_CMD_BASE = ("convert",)

@register_image_displayer("ueberzug")
class UeberzugImageDisplayer(ImageDisplayer):
    """Implementation of ImageDisplayer using ueberzug.
    Ueberzug can display images in a Xorg session.
    Does not work over ssh.
    """
    IMAGE_ID = 'preview'
    is_initialized = False

    def __init__(self):
        self.process = None

    def initialize(self):
        """start ueberzug"""
        if (self.is_initialized and self.process.poll() is None
                and not self.process.stdin.closed):
            return

        # We cannot close the process because that stops the preview.
        # pylint: disable=consider-using-with
        with open(os.devnull, "wb") as devnull:
            self.process = Popen(
                ["ueberzug", "layer", "--silent"],
                cwd=self.working_dir,
                stderr=devnull,
                stdin=PIPE,
                universal_newlines=True,
            )
        self.is_initialized = True

    def _execute(self, **kwargs):
        self.initialize()
        self.process.stdin.write(json.dumps(kwargs) + '\n')
        self.process.stdin.flush()

    # pylint: disable=too-many-positional-arguments
    def draw(self, path, start_x, start_y, width, height):
        self._execute(
            action='add',
            identifier=self.IMAGE_ID,
            x=start_x,
            y=start_y,
            max_width=width,
            max_height=height,
            path=path
        )

    def clear(self, start_x, start_y, width, height):
        if self.process and not self.process.stdin.closed:
            self._execute(action='remove', identifier=self.IMAGE_ID)

    def quit(self):
        if self.is_initialized and self.process.poll() is None:
            timer_kill = threading.Timer(1, self.process.kill, [])
            try:
                self.process.terminate()
                timer_kill.start()
                self.process.communicate()
            finally:
                timer_kill.cancel()
