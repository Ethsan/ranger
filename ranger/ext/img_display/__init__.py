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
)

from . import ueberzug, kitty, urxvt, terminology, sixel, iterm, w3m  # noqa: F401

__all__ = [
    "get_image_displayer",
    "ImageDisplayer",
    "ImageDisplayError",
    "ImgDisplayUnsupportedException",
]
