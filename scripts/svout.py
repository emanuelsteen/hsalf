# This script is a part of Hsalf.
#
# Copyright (c) 2011, Nam T. Nguyen
# Released under the MIT license

from hsalf import swf
from cStringIO import StringIO
import Image
import sys
import subprocess
import optparse


def list_stream(inp):
    fi = swf.SwfFile(inp)
    for tag in fi.iter_body():
        if isinstance(tag, swf.DefineVideoStreamTag):
            if tag.codec_id == swf.SCREEN_VIDEO_CODEC:
                print 'Found Screen Video stream ID', tag.character_id


def save_img(img, frame_nr, outp, format):
    if outp == '-':
        outp = sys.stdout
    else:
        outp += '{0:05d}.{1}'.format(frame_nr, format)
        outp = open(outp, 'wb')
    if format == 'rgb':
        outp.write(img.tostring())
    else:
        img.save(outp, format=format)


def extract_stream(inp, source_id, outp, format):
    fi = swf.SwfFile(inp)
    for tag in fi.iter_body():
        if isinstance(tag, swf.VideoFrameTag) and \
            tag.stream_id == source_id:
            data = StringIO(tag.video_data)
            svp = swf.ScreenVideoPacket().deserialize(data)
            if svp.frame_type == swf.KEY_FRAME:
                last_img = Image.new('RGB', (svp.image_width, svp.image_height))
            img = svp.to_image(last_img)
            save_img(img, tag.frame_num, outp, format)
            last_img = img


def main():
    parser = optparse.OptionParser()
    parser.add_option('-i', help='Input SWF file', metavar='FILE',
        dest='input')
    parser.add_option('-o', help='Output basename, a lone hyphen for stdout',
        metavar='FILE', dest='output')
    parser.add_option('-s', help='Stream ID', metavar='ID', type=int,
        dest='stream_id')
    parser.add_option('-f', help='Output format (PNG, JPG, rgb)',
        metavar='FORMAT', dest='format', default='png')
    options, args = parser.parse_args()
    if options.input is None:
        parser.error('Missing input file')
    if options.stream_id is None:
        list_stream(options.input)
    elif options.output is None:
        parser.error('Missing output file')
    else:
        # set stdout to binary in windows
        try:
            import os, msvcrt
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        except:
            pass
        extract_stream(options.input, options.stream_id, options.output,
            options.format)


if __name__ == '__main__':
    main()
