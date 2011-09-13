from cStringIO import StringIO

import zlib
import struct


KEY_FRAME = 1
INTER_FRAME = 2
DISPOSABLE_INTER_FRAME = 3

SORENSON_H263_CODEC = 2
SCREEN_VIDEO_CODEC = 3

LATIN, JAPANESE, KOREAN, SIMPLIFIED_CHINESE, TRADITIONAL_CHINESE = range(1, 6)

VIDEOFRAME = 61


class SwfException(Exception):
	'''The top most exception class in this module.'''
	pass


class IoSwfException(SwfException):
	'''Exception related to parsing/writing SWF.'''
	pass


class CorruptedSwfException(SwfException):
	'''Exception raised when SWF file is cannot be parsed.'''
	pass


def ensure_read(f, length):
	'''Reads exactly length bytes from f.

	Returns:
		length bytes from f.
	
	Raises:
		IoSwfException: If there is less than length bytes available.
	
	'''

	s = f.read(length)
	if len(s) != length:
		raise IoSwfException('Expected {0} bytes but only available {1} '
			'bytes.'.format(length, len(s)))
	return s


class BitReader(object):
	'''BitReader reads bits from a wrapped file-like object.'''

	def __init__(self, f):
		'''Construct a BitReader object from f.

		Args:
			f (file-like object): A file-like object to be wrapped.
		
		'''

		self.fio = f
		self.backlog = ''
	
	def read(self, length, sign=False):
		'''Reads length bits from wrapped file.

		Args:
			length (int): Number of bits to read.
			sign (bool): True to treat the bits as signed value.
		
		Returns:
			An integer value.
		
		'''

		if len(self.backlog) < length:
			more = length - len(self.backlog)
			bytes = (7 + more) // 8
			bits = ['{0:08b}'.format(ord(x)) for x in \
				ensure_read(self.fio, bytes)]
			self.backlog += ''.join(bits)
		start = 1 if sign else 0
		r = int(self.backlog[start : length], 2)
		if sign and self.backlog[0] == '1':
			# take two's complement
			r = -(2 ** (length - 1) - r)
		self.backlog = self.backlog[length : ]
		return r

	def sign_read(self, length):
		'''Reads length bits from wrapped file,
		treating it as signed value.

		Args:
			length (int): Number of bits to read.
		
		Returns:
			A signed integer value.
		
		Raises:
			ValueError: If length is less than 2.

		'''

		if length < 2:
			raise ValueError('signed value must have length greater than 1')
		return self.read(length, True)

	def unsign_read(self, length):
		'''Reads length bits from wrapped file,
		treating it as unsigned value.

		This is the same as calling `read(length, False)`.

		Args:
			length (int): Number of bits to read.
		
		Returns:
			An unsigned integer value.
		
		'''

		return self.read(length, False)
	

class BitWriter(object):
	'''BitWriter writes bits to a wrapped file-like object.'''

	def __init__(self, f):
		'''Constructs a BitWriter from f.

		Args:
			f (file-like object): A file-like object to write to.
		
		'''

		self.fio = f
		self.buffer = []
	
	def __del__(self):
		self.flush()
	
	def flush(self):
		'''Writes the buffer out to wrapped file.

		The buffer will be padded with enough 0 bits to make it byte-aligned.

		'''

		data = b''.join(self.buffer)
		remain = len(data) % 8
		if remain != 0:
			remain = 8 - remain
			data += b'0' * remain
		buf = []
		idx = 0
		while idx < len(data):
			c = chr(int(data[idx : idx + 8], 2))
			buf.append(c)
			idx += 8
		self.fio.write(b''.join(buf))
		self.fio.flush()
	
	@staticmethod
	def required_bits(*numbers):
		'''Returns the minimum number of bits required to represent any
		of the numbers as signed values.

		Args:
			numbers (sequence): A sequence of integer values.
		
		Returns:
			The mininum required bits.

		'''

		# min int32
		max_num = (-2) ** 31
		for num in numbers:
			# negative number?
			# take absolute value, minus 1
			# because -2 requires 1 bit to present, but 2 requires 2
			if num < 0:
				num = -num - 1
			if max_num < num:
				max_num = num
		return len('{0:b}'.format(max_num)) + 1
	
	def write(self, bits, number):
		'''Writes number to wrapped file as bits-bit value.

		Note that write does not flush. Consecutive calls to write
		will append bits to the buffer and will not byte-align it.

		Args:
			bits (int): Number of bits to represent number.
			number (int): The number to be written.
		
		'''

		if number < 0:
			number = 2 ** bits + number
		fmt = '{{0:0{0}b}}'.format(bits)
		self.buffer.append(fmt.format(number))


class SwfObject(object):
	'''An interface from which all SWF related objects are derived.

	Two methods must be provided are serialize and deserialize.

	'''

	def __init__(self):
		pass
	
	def serialize(self, f):
		'''Writes this object to file-like object f in specified format.

		Args:
			f (file-like object): A file to write to.
		
		'''

		raise NotImplemented()
	
	def deserialize(self, f):
		'''Populates self with data from a file-like object f.

		Args:
			f (file-like object): A file to read from.
		
		Returns:
			self: If deserialization succeeds.
			None: If not.
		
		'''

		raise NotImplemented()


class Fixed32(SwfObject):
	'''Represents a 16.16 fixed value according to SWF spec.'''

	def __init__(self, value=0):
		self.value = value

	def deserialize(self, f):
		value = struct.unpack('<i', f.read(4))[0]
		self.value = value / 65536.0
		return self
	
	def serialize(self, f):
		value = int(self.value * 65536.0)
		f.write(struct.pack('<i', value))


class String(SwfObject):
	'''Represents a String according to SWF spec.'''

	def __init__(self, value=''):
		pos = value.find('\x00')
		if pos >= 0:
			value = value[ : pos]
		self.value = value
	
	def deserialize(self, f, encoding='utf-8'):
		r = []
		while True:
			c = ensure_read(f, 1)
			if c == '\x00':
				break
			r.append(c)
		# version 6.0 or later defaults to utf-8
		self.value = b''.join(r).decode(encoding)
		return self
	
	def serialize(self, f, encoding='utf-8'):
		value = self.value.encode(encoding)
		f.write(value + '\x00')


class RgbColor(SwfObject):
	'''Represents an RGB color according to SWF spec.'''

	def __init__(self, r=0, g=0, b=0):
		self.r = r
		self.g = g
		self.b = b
	
	def deserialize(self, f):
		self.r, self.g, self.b = struct.unpack('<BBB', f.read(3))
		return self
	
	def serialize(self, f):
		f.write(struct.pack('<BBB', self.r, self.g, self.b))


class RgbaColor(SwfObject):
	'''Represents an RGBA color according to SWF spec.'''

	def __init__(self, r=0, g=0, b=0, a=0):		
		self.r = r
		self.g = g
		self.b = b
		self.a = a
	
	def deserialize(self, f):
		self.r, self.g, self.b, self.a = \
			struct.unpack('<BBBB', f.read(4))
		return self
	
	def serialize(self, f):
		f.write(struct.pack('<BBBB', self.r, self.g, self.b, self.a))


class Rect(SwfObject):
	'''Represents a RECT record according to SWF spec.'''

	def __init__(self):
		self.nbits = 0
		self.x_min = 0
		self.x_max = 0
		self.y_min = 0
		self.y_max = 0
	
	def deserialize(self, f):
		br = BitReader(f)
		nbits = br.unsign_read(5)
		self.x_min = br.sign_read(nbits)
		self.x_max = br.sign_read(nbits)
		self.y_min = br.sign_read(nbits)
		self.y_max = br.sign_read(nbits)
		return self
	
	def serialize(self, f):
		bw = BitWriter(f)
		nbits = BitWriter.required_bits(self.x_min, self.x_max,
			self.y_min, self.y_max)
		bw.write(5, nbits)
		bw.write(nbits, self.x_min)
		bw.write(nbits, self.x_max)
		bw.write(nbits, self.y_min)
		bw.write(nbits, self.y_max)
		bw.flush()
	
	def __repr__(self):
		return '%s%r' % (type(self).__name__, (
			self.x_min, self.x_max, self.y_min, self.y_max))


class Matrix(SwfObject):
	'''Represents a MATRIX record according to SWF spec.'''

	def __init__(self):
		self.scale = None
		self.rotate = None
		self.translate = [0, 0]

	def deserialize(self, f):
		br = BitReader(f)
		has_scale = br.unsign_read(1)
		if has_scale:
			scale_bits = br.unsign_read(5)
			scale_x = br.sign_read(scale_bits)
			scale_y = br.sign_read(scale_bits)
			self.scale = [scale_x / 65536.0, scale_y / 65536.0]
		has_rotate = br.unsign_read(1)
		if has_rotate:
			rotate_bits = br.unsign_read(5)
			rotate1 = br.sign_read(rotate_bits)
			rotate2 = br.sign_read(rotate_bits)
			self.rotate = [rotate1 / 65536.0, rotate2 / 65536.0]
		translate_bits = br.unsign_read(5)
		translate_x = br.sign_read(translate_bits)
		translate_y = br.sign_read(translate_bits)
		self.translate = [translate_x, translate_y]
		return self


class FileHeader(SwfObject):
	'''Represents the first 8 bytes of an SWF file.

	The attributes are:
		signature (string): Either 'FWS' or 'CWS'.
		version (int): Version of this SWF file.
		file_length (int): The length of the file, including this header.

	'''

	def __init__(self):
		self.signature = 'FWS'
		self.version = 7
		self.file_length = 0
	
	def deserialize(self, f):
		signature, version, length = \
			struct.unpack('<3sBI', f.read(8))
		if signature not in ('FWS', 'CWS'):
			raise SwfException('Invalid signature')
		self.signature = signature
		self.version = version
		return self
	
	def _compressed(self):
		if signature[0] == 'C':
			return True
		return False
	compressed = property(_compressed)

	def serialize(self, f):
		f.write(struct.pack('<3sBI', self.signature, self.version,
			self.file_length))
	

class FrameHeader(SwfObject):

	def __init__(self):
		self.frame_size = Rect()
		self.frame_rate = 0
		self.frame_count = 0

	def deserialize(self, f):
		size = Rect().deserialize(f)
		rate, count = struct.unpack('<HH', f.read(4))
		self.frame_size = size
		self.frame_rate = rate
		self.frame_count = count
		return self

	def serialize(self, f):
		self.frame_size.serialize(f)
		f.write(struct.pack('<HH', self.frame_rate, self.frame_count))


class Header(SwfObject):

	def __init__(self, file_header, frame_header):
		self.file_header = file_header
		self.frame_header = frame_header
	
	def deserialize(self, f):
		raise NotImplemented()
	
	def serialize(self, f):
		self.file_header.serialize(f)
		self.frame_header.serialize(f)


class Tag(SwfObject):
	
	def __init__(self, tag=None):
		if not tag:
			self.tag_code = 0
			self.tag_length = 0
		else:
			self.clone_tag(tag)

	def clone_tag(self, tag):
		self.tag_code = tag.tag_code
		self.tag_length = tag.tag_length
		return self
	
	def deserialize(self, f, tag=True):
		if tag:
			code_and_length = struct.unpack('<H', f.read(2))[0]
			self.tag_length = code_and_length & 0b111111
			self.tag_code = code_and_length >> 6
			if self.tag_length >= 63:
				self.tag_length = struct.unpack('<I', f.read(4))[0]
		self._deserialize(f)
		return self

	def _deserialize(self, f):
		pass

	def serialize(self, f, tag=True):
		if tag:
			code_and_length = self.tag_code << 6
			if self.tag_length < 63:
				code_and_length |= self.tag_length
				f.write(struct.pack('<H', code_and_length))
			else:
				code_and_length |= 63
				f.write(struct.pack('<HI', code_and_length, self.tag_length))
		self._serialize(f)
	
	def _serialize(self):
		pass


class UnknownTag(Tag):

	def __init__(self):
		self.data = ''
	
	def _deserialize(self, f):
		self.data = ensure_read(f, self.tag_length)

	def _serialize(self, f):
		f.write(data)


class ScreenVideoBlock(SwfObject):

	def __init__(self, width, height):
		self.width = width
		self.height = height
		self.pixels = []
	
	def __cmp__(self, other):
		if not isinstance(other, self.__class__):
			raise TypeError('Must be compared to a ScreenVideoBlock instance')
		return cmp((self.width, self.height, self.pixels),
			(other.width, other.height, other.pixels))
	
	def deserialize(self, f):
		br = BitReader(f)
		size = br.unsign_read(16)
		if size == 0:
			return None
		blk_data = f.read(size)
		blk_data = zlib.decompress(blk_data)
		blk_data = StringIO(blk_data)
		self.pixels = [0] * (self.width * self.height)
		pixel_nr = 0
		while pixel_nr < len(self.pixels):
			self.pixels[pixel_nr] = ScreenVideoPacket.BgrColor(). \
				deserialize(blk_data)
			pixel_nr += 1
		return self

	def serialize(self, f):
		bw = BitWriter(f)
		if not self.pixels:
			bw.write(16, 0)
			bw.flush()
		else:
			data = StringIO()
			for pixel in self.pixels:
				pixel.serialize(data)
			data = zlib.compress(data.getvalue())
			bw.write(16, len(data))
			bw.flush()
			f.write(data)


class ScreenVideoPacket(SwfObject):

	class BgrColor(SwfObject):

		def __init__(self, b=0, g=0, r=0):
			self.b = b
			self.g = g
			self.r = r

		def to_rgb_tuple(self):
			return (self.r, self.g, self.b)
		
		def from_rgb_tuple(self, rgb):
			self.r, self.g, self.b = rgb
		
		def __repr__(self):
			return '%s%r' % (type(self).__name__, (
				self.b, self.g, self.r))
		
		def __cmp__(self, other):
			if isinstance(other, self.__class__):
				return cmp((self.b, self.g, self.r),
					(other.b, other.g, other.r))
			raise TypeError('Must be compared to a BgrColor instance')

		def __hash__(self):
			return hash((self.b, self.g, self.r))
		
		def deserialize(self, f):
			self.b, self.g, self.r = struct.unpack('BBB', f.read(3))
			return self
		
		def serialize(self, f):
			f.write(struct.pack('BBB', self.b, self.g, self.r))

	def __init__(self):
		self.frame_type = KEY_FRAME
		self.codec_id = SCREEN_VIDEO_CODEC
		self.block_width = 0
		self.block_height = 0
		self.image_width = 0
		self.image_height = 0
		self.hoz_blk_cnt = 0
		self.ver_blk_cnt = 0
		self.block_count = 0
		self.image_blocks = []
	
	def deserialize(self, f):
		br = BitReader(f)
		self.frame_type = br.unsign_read(4)
		codec_id = br.unsign_read(4)
		if codec_id != SCREEN_VIDEO_CODEC:
			raise SwfException('ScreenVideoPacket is only for Screen Video codec')
		self.block_width = (br.unsign_read(4) + 1) * 16
		self.image_width = br.unsign_read(12)
		self.block_height = (br.unsign_read(4) + 1) * 16
		self.image_height = br.unsign_read(12)
		self.prepare_blocks()
		self.fill_blocks(f)
		return self
	
	def prepare_blocks(self):
		self.hoz_blk_cnt = (self.image_width + self.block_width - 1) // \
			self.block_width
		self.ver_blk_cnt = (self.image_height + self.block_height - 1) // \
			self.block_height
		self.block_count = self.hoz_blk_cnt * self.ver_blk_cnt
		self.image_blocks = [None] * self.block_count

	def get_block_dimension(self, block_nr):
		row = block_nr // self.hoz_blk_cnt
		col = block_nr % self.hoz_blk_cnt
		width = self.block_width if col < self.hoz_blk_cnt - 1 else \
			self.image_width - col * self.block_width
		height = self.block_height if row < self.ver_blk_cnt - 1 else \
			self.image_height - row * self.block_height
		return width, height

	def fill_blocks(self, f):
		for block_nr in xrange(self.block_count):
			width, height = self.get_block_dimension(block_nr)
			svb = ScreenVideoBlock(width, height).deserialize(f)
			self.image_blocks[block_nr] = svb

	def to_image(self, image):
		pixel_access = image.load()
		for block_nr, svb in enumerate(self.image_blocks):
			if not svb:
				continue
			row = block_nr // self.hoz_blk_cnt
			col = block_nr % self.hoz_blk_cnt
			start_y = self.image_height - (row * self.block_height) - 1
			start_x = col * self.block_width
			row = col = 0
			for pixel in svb.pixels:
				if pixel:
					y = start_y - row
					x = start_x + col
					pixel_access[x, y] = pixel.to_rgb_tuple()
				col += 1
				if col >= svb.width:
					row += 1
					col = 0
		return image
	
	def from_image(self, img, previous_frame=None,
		block_width=32, block_height=32):
		'''Fills self with data from img.

		Fills the current object with data from img. If previous_frame is
		None, this frame will be a keyframe. Otherwise, previous_frame must
		be a ScreenVideoPacket, then this frame will be an interframe. Delta
		data are calculated from img and previous_frame.

		Args:
			img (Image): A loaded RGB image.
			previous_frame (ScreenVideoPacket): The previous frame data, or
				None if this frame is a keyframe.
			block_width (int): The block width.
			block_height (int): The block height.
		
		Returns:
			None
		
		Raises:
			SwfException: If previous frame is not a ScreenVideoPacket, or
				previous_frame size is different from this frame, or
				block sizes are not multiple of 16, or
				img is not an RGB image.

		'''
		# interfame
		if previous_frame:
			if not isinstance(previous_frame, ScreenVideoPacket):
				raise SwfException('Previous frame must be a Screen Video frame')
			if (previous_frame.image_width, previous_frame.image_height) != \
				img.size:
				raise SwfException('Mismatched frame size')
			self.block_width = previous_frame.block_width
			self.block_height = previous_frame.block_height
			self.frame_type = INTER_FRAME
		# key frame
		else:
			self.block_width = block_width
			self.block_height = block_height
			self.frame_type = KEY_FRAME
		if (self.block_width % 16) != 0 or (self.block_height % 16) != 0:
			raise SwfException('Block size must be multiple of 16')
		if img.mode != 'RGB':
			raise SwfException('Source image must be in RGB mode')
		self.image_width, self.image_height = img.size
		self.prepare_blocks()
		self.fill_blocks_from_image(img, previous_frame)
	
	def fill_blocks_from_image(self, img, previous_frame=None):
		for block_nr in xrange(self.block_count):
			width, height = self.get_block_dimension(block_nr)
			svb = ScreenVideoBlock(width, height)

			row = block_nr // self.hoz_blk_cnt
			col = block_nr % self.hoz_blk_cnt
			start_x = col * self.block_width
			stop_y = img.size[1] - row * self.block_width

			crop = img.crop((start_x, stop_y - height, start_x + width,
				stop_y))
			pixels = list(crop.getdata())

			idx = width * (height - 1)
			pix_idx = 0
			while idx >= 0:
				for pix in pixels[idx : idx + width]:
					svb.pixels[pix_idx] = ScreenVideoPacket.BgrColor(). \
						from_rgb_tuple(pix)
					pix_idx += 1
				idx -= width
			assert(pix_idx == len(svb.pixels))

			# check if this block and the previous one is the same
			# if it is, we do not need this block
			if previous_frame and \
				previous_frame.image_blocks[block_nr] == svb:
				svb = None
			self.image_blocks[block_nr] = svb

	def __repr__(self):
		return '%s%r' % (type(self).__name__, (
			self.image_width, self.image_height))


class VideoFrameTag(Tag):

	def __init__(self):
		self.tag_code = VIDEOFRAME
		self.stream_id = 0
		self.frame_num = 0
		self.video_data = ''
	
	def _deserialize(self, f):
		if self.tag_length < 4:
			raise CorruptedSwfException()
		self.stream_id, self.frame_num = struct.unpack('<HH', f.read(4))
		self.video_data = ensure_read(f, self.tag_length - 4)


class SwfFile(SwfObject):

	decoders = {
		VIDEOFRAME: VideoFrameTag,
	}

	def __init__(self, file_name=None):
		self.header = None
		self.file = None
		if file_name:
			self.load_header(file_name)

	def close(self):
		self.file.close()
	
	def __del__(self):
		if self.file:
			self.file.close()

	def load_header(self, file_name):
		self.file = open(file_name, 'rb')
		fih = FileHeader().deserialize(self.file)
		if fih.compressed:
			if fih.version < 6:
				raise SwfException('Compression is only supported '
					'from version 6')
			compressed = self.file.read()
			self.file.close()
			decomp = zlib.decompress(compressed)
			self.file = StringIO(decomp)
		frh = FrameHeader().deserialize(self.file)
		self.header = Header(fih, frh)
	
	def load(self, file_name, body=True):
		self.load_header(file_name)
		if body:
			self.body = [tag for tag in self.iter_body()]

	def iter_body(self):
		while True:
			try:
				tag = Tag().deserialize(self.file)
			except IoSwfException:
				if last_tag.tag_code == 0:
					break
				raise CorruptedSwfException()
			clz = SwfFile.decoders.get(tag.tag_code, UnknownTag)
			tag = clz().clone_tag(tag).deserialize(self.file, False)
			yield tag
			last_tag = tag
	
	def save(self, file_name):
		raise NotImplemented()
