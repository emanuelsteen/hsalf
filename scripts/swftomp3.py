# This script is a part of Hsalf.
#
# Copyright (c) 2011, Nam T. Nguyen
# Released under the MIT license

from hsalf import swf
from cStringIO import StringIO

import optparse


def list_stream(inp):
	stream_id = 0
	fi = swf.SwfFile(inp)
	for tag in fi.iter_body():
		if isinstance(tag, swf.SoundStreamHeadTag):
			if tag.stream_sound_compression == swf.SND_MP3:
				stream_id += 1
				print 'Found MP3 stream ID', stream_id

def extract_stream(inp, stream_id, outp):
	current_id = 0
	fi = fo = None
	try:
		fi = swf.SwfFile(inp)
		fo = open(outp, 'wb')
		for tag in fi.iter_body():
			if isinstance(tag, swf.SoundStreamHeadTag):
				if tag.stream_sound_compression == swf.SND_MP3:
					current_id += 1
			if isinstance(tag, swf.SoundStreamBlockTag) and \
				current_id == stream_id:
				data = StringIO(tag.sound_data)
				mp3 = swf.Mp3StreamSoundData().deserialize(data)
				data = mp3.sound_data.frames
				fo.write(data)
	finally:
		for f in (fo, fi):
			if f:
				f.close()

def main():
	parser = optparse.OptionParser()
	parser.add_option('-i', help='Input SWF file', metavar='FILE',
		dest='input')
	parser.add_option('-o', help='Output MP3 file', metavar='FILE',
		dest='output')
	parser.add_option('-s', help='Stream ID', metavar='ID', type=int,
		dest='stream_id')
	options, args = parser.parse_args()
	if options.input is None:
		parser.error('Missing input file')
	if options.stream_id is None:
		list_stream(options.input)
	elif options.output is None:
		parser.error('Missing output file')
	else:
		extract_stream(options.input, options.stream_id, options.output)

if __name__ == '__main__':
	main()
