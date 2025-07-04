# This file is part of ranger, the console file manager.
# License: GNU GPL version 3, see the file "AUTHORS" for details.
# Author: Emanuel Guevel, 2013
# Author: Delisa Mason, 2015

"""Interface for drawing images into the console

This module provides functions to draw images in the terminal using supported
implementations.
"""

from __future__ import absolute_import, division, print_function

import curses
import fcntl
import os
import struct
import sys
from collections import defaultdict

import termios
from contextlib import contextmanager

from ranger.core.shared import SettingsAware

# Helper functions shared between the previewers (make them static methods of the base class?)


@contextmanager
def temporarily_moved_cursor(to_y, to_x):
    """Common boilerplate code to move the cursor to a drawing area. Use it as:
    with temporarily_moved_cursor(dest_y, dest_x):
        your_func_here()"""
    curses.putp(curses.tigetstr("sc"))
    move_cur(to_y, to_x)
    yield
    curses.putp(curses.tigetstr("rc"))
    sys.stdout.flush()


# this is excised since Terminology needs to move the cursor multiple times
def move_cur(to_y, to_x):
    tparm = curses.tparm(curses.tigetstr("cup"), to_y, to_x)
    # on python2 stdout is already in binary mode, in python3 is accessed via buffer
    bin_stdout = getattr(sys.stdout, "buffer", sys.stdout)
    bin_stdout.write(tparm)


def get_terminal_size():
    farg = struct.pack("HHHH", 0, 0, 0, 0)
    fd_stdout = sys.stdout.fileno()
    fretint = fcntl.ioctl(fd_stdout, termios.TIOCGWINSZ, farg)
    return struct.unpack("HHHH", fretint)


def get_font_dimensions():
    """
    Get the height and width of a character displayed in the terminal in
    pixels.
    """
    rows, cols, xpixels, ypixels = get_terminal_size()
    return (xpixels // cols), (ypixels // rows)


def image_fit_width(
    width, height, max_cols, max_rows, *, font_width=None, font_height=None
):
    if font_width is None or font_height is None:
        font_width, font_height = get_font_dimensions()

    max_width = font_width * max_cols
    max_height = font_height * max_rows
    if height > max_height:
        if width > max_width:
            width_scale = max_width / width
            height_scale = max_height / height
            min_scale = min(width_scale, height_scale)
            return width * min_scale
        else:
            scale = max_height / height
            return width * scale
    elif width > max_width:
        scale = max_width / width
        return width * scale
    else:
        return width


class ImageDisplayError(Exception):
    pass


class ImgDisplayUnsupportedException(Exception, SettingsAware):
    def __init__(self, message=None):
        if message is None:
            message = (
                '"{0}" does not appear to be a valid setting for'
                " preview_images_method."
            ).format(self.settings.preview_images_method)
        super(ImgDisplayUnsupportedException, self).__init__(message)


def fallback_image_displayer():
    """Simply makes some noise when chosen. Temporary fallback behavior."""

    raise ImgDisplayUnsupportedException


IMAGE_DISPLAYER_REGISTRY = defaultdict(fallback_image_displayer)


def register_image_displayer(nickname=None):
    """Register an ImageDisplayer by nickname if available."""

    def decorator(image_displayer_class):
        if nickname:
            registry_key = nickname
        else:
            registry_key = image_displayer_class.__name__
        IMAGE_DISPLAYER_REGISTRY[registry_key] = image_displayer_class
        return image_displayer_class

    return decorator


def get_image_displayer(registry_key):
    image_displayer_class = IMAGE_DISPLAYER_REGISTRY[registry_key]
    return image_displayer_class()


class ImageDisplayer(object):
    """Image display provider functions for drawing images in the terminal"""

    working_dir = os.environ.get("XDG_RUNTIME_DIR", os.path.expanduser("~") or None)

    # pylint: disable=too-many-positional-arguments
    def draw(self, path, start_x, start_y, width, height):
        """Draw an image at the given coordinates."""

    def clear(self, start_x, start_y, width, height):
        """Clear a part of terminal display."""

    def quit(self):
        """Cleanup and close"""
