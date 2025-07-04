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
    temporarily_moved_cursor,
    ImageDisplayer,
    ImageDisplayError,
    ImgDisplayUnsupportedException,
    register_image_displayer,
)

from . import urxvt, terminology, sixel, iterm, w3m  # noqa: F401

__all__ = [
    "get_image_displayer",
    "ImageDisplayer",
    "ImageDisplayError",
    "ImgDisplayUnsupportedException",
]

import base64
import fcntl
import os
import struct
import sys
import warnings
import json
import threading
from subprocess import Popen, PIPE 

import termios
import codecs
from tempfile import gettempdir, NamedTemporaryFile

from ranger.core.shared import FileManagerAware
from ranger.ext.which import which


if which("magick"):
    # Magick >= 7
    MAGICK_CONVERT_CMD_BASE = ("magick",)
else:
    # Magick < 7
    MAGICK_CONVERT_CMD_BASE = ("convert",)

@register_image_displayer("kitty")
class KittyImageDisplayer(ImageDisplayer, FileManagerAware):
    """Implementation of ImageDisplayer for kitty (https://github.com/kovidgoyal/kitty/)
    terminal. It uses the built APC to send commands and data to kitty,
    which in turn renders the image. The APC takes the form
    '\033_Gk=v,k=v...;bbbbbbbbbbbbbb\033\\'
       |   ---------- --------------  |
    escape code  |             |    escape code
                 |  base64 encoded payload
        key: value pairs as parameters
    For more info please head over to :
        https://github.com/kovidgoyal/kitty/blob/master/graphics-protocol.asciidoc"""
    protocol_start = b'\x1b_G'
    protocol_end = b'\x1b\\'
    # we are going to use stdio in binary mode a lot, so due to py2 -> py3
    # differences is worth to do this:
    stdbout = getattr(sys.stdout, 'buffer', sys.stdout)
    stdbin = getattr(sys.stdin, 'buffer', sys.stdin)
    # counter for image ids on kitty's end
    image_id = 0
    # we need to find out the encoding for a path string, ascii won't cut it
    try:
        fsenc = sys.getfilesystemencoding()  # returns None if standard utf-8 is used
        # throws LookupError if can't find the codec, TypeError if fsenc is None
        codecs.lookup(fsenc)
    except (LookupError, TypeError):
        fsenc = 'utf-8'

    def __init__(self):
        # the rest of the initializations that require reading stdio or raising exceptions
        # are delayed to the first draw call, since curses
        # and ranger exception handler are not online at __init__() time
        self.needs_late_init = True
        # to init in _late_init()
        self.backend = None
        self.stream = None
        self.pix_row, self.pix_col = (0, 0)
        self.temp_file_dir = None  # Only used when streaming is not an option

    def _late_init(self):
        # query terminal for kitty graphics protocol support
        # https://sw.kovidgoyal.net/kitty/graphics-protocol/#querying-support-and-available-transmission-mediums
        # combined with automatic check if we share the filesystem using a dummy file
        with NamedTemporaryFile() as tmpf:
            tmpf.write(bytearray([0xFF] * 3))
            tmpf.flush()
            # kitty graphics protocol query
            for cmd in self._format_cmd_str(
                    {'a': 'q', 'i': 1, 'f': 24, 't': 'f', 's': 1, 'v': 1, 'S': 3},
                    payload=base64.standard_b64encode(tmpf.name.encode(self.fsenc))):
                self.stdbout.write(cmd)
            sys.stdout.flush()
            # VT100 Primary Device Attributes (DA1) query
            self.stdbout.write(b'\x1b[c')
            sys.stdout.flush()
            # read response(s); DA1 response should always be last
            resp = b''
            #          (DA1 resp start   )     (DA1 resp end     )
            while not ((b'\x1b[?' in resp) and (resp[-1:] == b'c')):
                resp += self.stdbin.read(1)

        # check whether kitty graphics protocol query was acknowledged
        # NOTE: this catches tmux too, no special case needed!
        if not resp.startswith(self.protocol_start):
            raise ImgDisplayUnsupportedException(
                'terminal did not respond to kitty graphics query; disabling')
        # strip resp down to just the kitty graphics protocol response
        resp = resp[:resp.find(self.protocol_end) + 1]

        # set the transfer method based on the response
        # if resp.find(b'OK') != -1:
        if b'OK' in resp:
            self.stream = False
            self.temp_file_dir = os.path.join(
                gettempdir(), "tty-graphics-protocol"
            )
            try:
                os.mkdir(self.temp_file_dir)
            except OSError:
                # COMPAT: Python 2.7 does not define FileExistsError so we have
                # to check whether the problem is the directory already being
                # present. This is prone to race conditions, TOCTOU.
                if not os.path.isdir(self.temp_file_dir):
                    raise ImgDisplayUnsupportedException(
                        "Could not create temporary directory for previews : {d}".format(
                            d=self.temp_file_dir
                        )
                    )
        elif b'EBADF' in resp:
            self.stream = True
        else:
            raise ImgDisplayUnsupportedException(
                'unexpected response from terminal emulator: {r}'.format(r=resp))

        # get the image manipulation backend
        try:
            # pillow is the default since we are not going
            # to spawn other processes, so it _should_ be faster
            import PIL.Image
            self.backend = PIL.Image
        except ImportError:
            raise ImageDisplayError("previews using kitty graphics require PIL (pillow)")
            # TODO: implement a wrapper class for Imagemagick process to
            # replicate the functionality we use from im

        # get dimensions of a cell in pixels
        ret = fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ,
                          struct.pack('HHHH', 0, 0, 0, 0))
        n_cols, n_rows, x_px_tot, y_px_tot = struct.unpack('HHHH', ret)
        self.pix_row, self.pix_col = x_px_tot // n_rows, y_px_tot // n_cols
        self.needs_late_init = False

    # pylint: disable=too-many-positional-arguments
    def draw(self, path, start_x, start_y, width, height):
        self.image_id += 1
        # dictionary to store the command arguments for kitty
        # a is the display command, with T going for immediate output
        # i is the id entifier for the image
        cmds = {'a': 'T', 'i': self.image_id}
        # sys.stderr.write('{0}-{1}@{2}x{3}\t'.format(
        #     start_x, start_y, width, height))

        # finish initialization if it is the first call
        if self.needs_late_init:
            self._late_init()

        with warnings.catch_warnings(record=True):  # as warn:
            warnings.simplefilter('ignore', self.backend.DecompressionBombWarning)
            image = self.backend.open(path)
            # TODO: find a way to send a message to the user that
            # doesn't stop the image from displaying
            # if warn:
            #     raise ImageDisplayError(str(warn[-1].message))
        box = (width * self.pix_row, height * self.pix_col)

        if image.width > box[0] or image.height > box[1]:
            scale = min(box[0] / image.width, box[1] / image.height)
            image = image.resize((int(scale * image.width), int(scale * image.height)),
                                 self.backend.LANCZOS)  # pylint: disable=no-member

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert(
                "RGBA" if "transparency" in image.info else "RGB"
            )
        # start_x += ((box[0] - image.width) // 2) // self.pix_row
        # start_y += ((box[1] - image.height) // 2) // self.pix_col
        if self.stream:
            # encode the whole image as base64
            # TODO: implement z compression
            # to possibly increase resolution in sent image
            # t: transmissium medium, 'd' for embedded
            # f: size of a pixel fragment (8bytes per color)
            # s, v: size of the image to recompose the flattened data
            # c, r: size in cells of the viewbox
            cmds.update({'t': 'd', 'f': len(image.getbands()) * 8,
                         's': image.width, 'v': image.height, })
            payload = base64.standard_b64encode(
                bytearray().join(map(bytes, image.getdata())))
        else:
            # put the image in a temporary png file
            # t: transmissium medium, 't' for temporary file (kitty will delete it for us)
            # f: size of a pixel fragment (100 just mean that the file is png encoded,
            #       the only format except raw RGB(A) bitmap that kitty understand)
            # c, r: size in cells of the viewbox
            cmds.update({'t': 't', 'f': 100, })
            with NamedTemporaryFile(
                prefix='ranger_thumb_',
                suffix='.png',
                dir=self.temp_file_dir,
                delete=False,
            ) as tmpf:
                image.save(tmpf, format='png', compress_level=0)
                payload = base64.standard_b64encode(tmpf.name.encode(self.fsenc))

        with temporarily_moved_cursor(int(start_y), int(start_x)):
            for cmd_str in self._format_cmd_str(cmds, payload=payload):
                self.stdbout.write(cmd_str)
        # catch kitty answer before the escape codes corrupt the console
        resp = b''
        while resp[-2:] != self.protocol_end:
            resp += self.stdbin.read(1)
        if b'OK' in resp:
            return
        else:
            raise ImageDisplayError('kitty graphics protocol replied "{r}"'.format(r=resp))

    def clear(self, start_x, start_y, width, height):
        # let's assume that every time ranger call this
        # it actually wants just to remove the previous image
        # TODO: implement this using the actual x, y, since the protocol
        #       supports it
        cmds = {'a': 'd', 'i': self.image_id}
        for cmd_str in self._format_cmd_str(cmds):
            self.stdbout.write(cmd_str)
        self.stdbout.flush()
        # kitty doesn't seem to reply on deletes, checking like we do in draw()
        # will slows down scrolling with timeouts from select
        self.image_id = max(0, self.image_id - 1)
        self.fm.ui.win.redrawwin()
        self.fm.ui.win.refresh()

    def _format_cmd_str(self, cmd, payload=None, max_slice_len=2048):
        central_blk = ','.join(["{k}={v}".format(k=k, v=v)
                                for k, v in cmd.items()]).encode('ascii')
        if payload is not None:
            # we add the m key to signal a multiframe communication
            # appending the end (m=0) key to a single message has no effect
            while len(payload) > max_slice_len:
                payload_blk, payload = payload[:max_slice_len], payload[max_slice_len:]
                yield self.protocol_start + \
                    central_blk + b',m=1;' + payload_blk + \
                    self.protocol_end
            yield self.protocol_start + \
                central_blk + b',m=0;' + payload + \
                self.protocol_end
        else:
            yield self.protocol_start + central_blk + b';' + self.protocol_end

    def quit(self):
        # clear all remaining images, then check if all files went through or
        # are orphaned
        while self.image_id >= 1:
            self.clear(0, 0, 0, 0)
        # for k in self.temp_paths:
        #     try:
        #         os.remove(self.temp_paths[k])
        #     except (OSError, IOError):
        #         continue


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
