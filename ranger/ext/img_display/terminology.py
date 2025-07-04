# This file is part of ranger, the console file manager.
# License: GNU GPL version 3, see the file "AUTHORS" for details.

from __future__ import absolute_import, division, print_function

import sys

from ranger.core.shared import FileManagerAware

from .displayer import (
    register_image_displayer,
    ImageDisplayer,
    temporarily_moved_cursor,
    move_cur,
)


@register_image_displayer("terminology")
class TerminologyImageDisplayer(ImageDisplayer, FileManagerAware):
    """Implementation of ImageDisplayer using terminology image display support
    (https://github.com/billiob/terminology).

    Ranger must be running in terminology for this to work.
    Doesn't work with TMUX :/
    """

    def __init__(self):
        self.display_protocol = "\033"
        self.close_protocol = "\000"

    # pylint: disable=too-many-positional-arguments
    def draw(self, path, start_x, start_y, width, height):
        with temporarily_moved_cursor(start_y, start_x):
            # Write intent
            sys.stdout.write("%s}ic#%d;%d;%s%s" % (
                self.display_protocol,
                width, height,
                path,
                self.close_protocol))

            # Write Replacement commands ('#')
            for y in range(0, height):
                move_cur(start_y + y, start_x)
                sys.stdout.write("%s}ib%s%s%s}ie%s\n" % (  # needs a newline to work
                    self.display_protocol,
                    self.close_protocol,
                    "#" * width,
                    self.display_protocol,
                    self.close_protocol))

    def clear(self, start_x, start_y, width, height):
        self.fm.ui.win.redrawwin()
        self.fm.ui.win.refresh()

    def quit(self):
        self.clear(0, 0, 0, 0)
