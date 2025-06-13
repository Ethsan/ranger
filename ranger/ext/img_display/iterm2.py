# This file is part of ranger, the console file manager.
# License: GNU GPL version 3, see the file "AUTHORS" for details.

from __future__ import absolute_import, division, print_function

import base64
import os
import struct
import sys

from ranger import PY3
from ranger.core.shared import FileManagerAware

from .displayer import (
    image_fit_width,
    register_image_displayer,
    ImageDisplayer,
    temporarily_moved_cursor,
)


@register_image_displayer("iterm2")
class ITerm2ImageDisplayer(ImageDisplayer, FileManagerAware):
    """Implementation of ImageDisplayer using iTerm2 image display support
    (http://iterm2.com/images.html).

    Ranger must be running in iTerm2 for this to work.
    """

    # pylint: disable=too-many-positional-arguments
    def draw(self, path, start_x, start_y, width, height):
        with temporarily_moved_cursor(start_y, start_x):
            sys.stdout.write(self._generate_iterm2_input(path, width, height))

    def clear(self, start_x, start_y, width, height):
        self.fm.ui.win.redrawwin()
        self.fm.ui.win.refresh()

    def quit(self):
        self.clear(0, 0, 0, 0)

    def _generate_iterm2_input(self, path, max_cols, max_rows):
        """Prepare the image content of path for image display in iTerm2"""
        image_width, image_height = self._get_image_dimensions(path)
        if max_cols == 0 or max_rows == 0 or image_width == 0 or image_height == 0:
            return ""
        image_width = self._fit_width(
            image_width, image_height, max_cols, max_rows)
        content, byte_size = self._encode_image_content(path)
        display_protocol = "\033"
        close_protocol = "\a"
        if os.environ["TERM"].startswith(("screen", "tmux")):
            display_protocol += "Ptmux;\033\033"
            close_protocol += "\033\\"

        text = "{0}]1337;File=inline=1;preserveAspectRatio=0;size={1};width={2}px:{3}{4}\n".format(
            display_protocol,
            str(byte_size),
            str(int(image_width)),
            content,
            close_protocol)
        return text

    def _fit_width(self, width, height, max_cols, max_rows):
        return image_fit_width(
            width, height, max_cols, max_rows,
            font_width=self.fm.settings.iterm2_font_width,
            font_height=self.fm.settings.iterm2_font_height
        )

    @staticmethod
    def _encode_image_content(path):
        """Read and encode the contents of path"""
        with open(path, 'rb') as fobj:
            content = fobj.read()
            return base64.b64encode(content).decode('utf-8'), len(content)

    @staticmethod
    def imghdr_what(path):
        """Replacement for the deprecated imghdr module"""
        with open(path, "rb") as img_file:
            header = img_file.read(32)
            if header[6:10] in (b'JFIF', b'Exif'):
                return 'jpeg'
            elif header[:4] == b'\xff\xd8\xff\xdb':
                return 'jpeg'
            elif header.startswith(b'\211PNG\r\n\032\n'):
                return 'png'
            if header[:6] in (b'GIF87a', b'GIF89a'):
                return 'gif'
            else:
                return None

    @staticmethod
    def _get_image_dimensions(path):
        """Determine image size using imghdr"""
        with open(path, 'rb') as file_handle:
            file_header = file_handle.read(24)
            image_type = ITerm2ImageDisplayer.imghdr_what(path)
            if len(file_header) != 24:
                return 0, 0
            if image_type == 'png':
                check = struct.unpack('>i', file_header[4:8])[0]
                if check != 0x0d0a1a0a:
                    return 0, 0
                width, height = struct.unpack('>ii', file_header[16:24])
            elif image_type == 'gif':
                width, height = struct.unpack('<HH', file_header[6:10])
            elif image_type == 'jpeg':
                unreadable = OSError if PY3 else IOError
                try:
                    file_handle.seek(0)
                    size = 2
                    ftype = 0
                    while not 0xc0 <= ftype <= 0xcf:
                        file_handle.seek(size, 1)
                        byte = file_handle.read(1)
                        while ord(byte) == 0xff:
                            byte = file_handle.read(1)
                        ftype = ord(byte)
                        size = struct.unpack('>H', file_handle.read(2))[0] - 2
                    file_handle.seek(1, 1)
                    height, width = struct.unpack('>HH', file_handle.read(4))
                except unreadable:
                    height, width = 0, 0
            else:
                return 0, 0
        return width, height
