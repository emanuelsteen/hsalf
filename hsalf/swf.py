from cStringIO import StringIO

import zlib
import struct


KEY_FRAME = 1
INTER_FRAME = 2
DISPOSABLE_INTER_FRAME = 3

SORENSON_H263_CODEC = 2
SCREEN_VIDEO_CODEC = 3

LATIN, JAPANESE, KOREAN, SIMPLIFIED_CHINESE, TRADITIONAL_CHINESE = range(1, 6)

SND_ADPCM = 1
SND_MP3 = 2

SND_MONO = 0
SND_STEREO = 1

SET_BACKGROUND_COLOR = 9
SOUND_STREAM_HEAD = 18
SOUND_STREAM_BLOCK = 19
PLACE_OBJECT_2 = 26
VIDEO_FRAME = 61


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

		if not self.buffer:
			return
		data = b''.join(self.buffer)
		self.buffer = []
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
		if translate_bits > 0:
			self.translate[0] = br.sign_read(translate_bits)
			self.translate[1] = br.sign_read(translate_bits)
		return self

	def serialize(self, f):
		bw = BitWriter(f)
		if self.scale is not None:
			bw.write(1, 1)
			bits = BitWriter.required_bits(*self.scale)
			bw.write(5, bits)
			bw.write(bits, self.scale[0])
			bw.write(bits, self.scale[1])
		else:
			bw.write(1, 0)
		if self.rotate is not None:
			bw.write(1, 1)
			bits = BitWriter.required_bits(*self.rotate)
			bw.write(5, bits)
			bw.write(bits, self.rotate[0])
			bw.write(bits, self.rotate[1])
		else:
			bw.write(1, 0)
		if self.translate == [0, 0]:
			bw.write(5, 0)
		else:
			bits = BitWriter.required_bits(*self.translate)
			bw.write(5, bits)
			bw.write(bits, self.translate[0])
			bw.write(bits, self.translate[1])
		bw.flush()


class ColorTransform(SwfObject):
	'''Represents CXFORM structure.

	Attributes:
		mult_term (list of int): Red, green, and blue mult terms.
		add_term (list of int): Red, green, and blue add terms.

	'''

	def __init__(self):
		self.mult_term = None
		self.add_term = None
	
	def deserialize(self, f):
		br = BitReader(f)
		has_add = br.unsign_read(1)
		has_mult = br.unsign_read(1)
		nbits = br.unsign_read(4)
		if has_mult:
			self.mult_term = [br.sign_read(nbits),
				br.sign_read(nbits), br.sign_read(nbits)]
		if has_add:
			self.add_term = [br.sign_read(nbits),
				br.sign_read(nbits), br.sign_read(nbits)]
		return self
	
	def serialize(self, f):
		bw = BitWriter(f)
		bits = [self.add_term is not None, self.mult_term is not None]
		for bit in bits:
			bw.write(1, bit)
		numbers = self.add_term if self.add_term is not None else []
		numbers.extend(self.mult_term if self.mult_term is not None else [])
		nbits = BitWriter.required_bits(*numbers)
		bw.write(4, nbits)
		if bits[1]:
			bw.write(nbits, self.mult_term[0])
			bw.write(nbits, self.mult_term[1])
			bw.write(nbits, self.mult_term[2])
		if bits[0]:
			bw.write(nbits, self.add_term[0])
			bw.write(nbits, self.add_term[1])
			bw.write(nbits, self.add_term[2])


class ColorTransformWithAlpha(SwfObject):
	'''Represents CXFORMWITHALPHA structure.

	Attributes:
		mult_term (list of int): Red, green, blue, alpha mult terms.
		add_term (list of int): Red, green, blue, alpha add terms.

	'''

	def __init__(self):
		self.mult_term = None
		self.add_term = None
	
	def deserialize(self, f):
		br = BitReader(f)
		has_add = br.unsign_read(1)
		has_mult = br.unsign_read(1)
		nbits = br.unsign_read(4)
		if has_mult:
			self.mult_term = [br.sign_read(nbits), br.sign_read(nbits),
				br.sign_read(nbits), br.sign_read(nbits)]
		if has_add:
			self.add_term = [br.sign_read(nbits), br.sign_read(nbits),
			br.sign_read(nbits), br.sign_read(nbits)]
		return self
	
	def serialize(self, f):
		bw = BitWriter(f)
		bits = [self.add_term is not None, self.mult_term is not None]
		for bit in bits:
			bw.write(1, bit)
		numbers = self.add_term if self.add_term is not None else []
		numbers.extend(self.mult_term if self.mult_term is not None else [])
		nbits = BitWriter.required_bits(*numbers)
		bw.write(4, nbits)
		if bits[1]:
			bw.write(nbits, self.mult_term[0])
			bw.write(nbits, self.mult_term[1])
			bw.write(nbits, self.mult_term[2])
			bw.write(nbits, self.mult_term[3])
		if bits[0]:
			bw.write(nbits, self.add_term[0])
			bw.write(nbits, self.add_term[1])
			bw.write(nbits, self.add_term[2])
			bw.write(nbits, self.add_term[3])


class FileHeader(SwfObject):
	'''Represents the first 8 bytes of an SWF file.

	Attributes:
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
		self.file_length = length
		return self
	
	def _get_compressed(self):
		if self.signature[0] == 'C':
			return True
		return False
	def _set_compressed(self, b):
		if b:
			self.signature = 'CWS'
		else:
			self.signature = 'FWS'
	compressed = property(_get_compressed, _set_compressed)

	def serialize(self, f):
		f.write(struct.pack('<3sBI', self.signature, self.version,
			self.file_length))
	

class FrameHeader(SwfObject):
	'''Represents the second part of SWFHEADER.

	Attributes:
		frame_size (Rect): Frame size, in twips.
		frame_rate (int): Number of frames per second.
		frame_count (int): Number of frames.
	
	'''

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
	'''Represents the full header record.

	Attributes:
		file_header (FileHeader): File header.
		frame_header (FrameHeader): Frame header.
	
	'''

	def __init__(self, file_header, frame_header):
		self.file_header = file_header
		self.frame_header = frame_header
	
	def deserialize(self, f):
		raise NotImplemented()
	
	def serialize(self, f):
		self.file_header.serialize(f)
		self.frame_header.serialize(f)


class Tag(SwfObject):
	'''Represents an SWF tag.

	Attributes:
		tag_code (int): The tag code.
		tag_length (int): The tag length, excluding tag_code and tag_length.
	
	'''
	
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
		'''Loads this tag from file-like object f.

		Args:
			f (file-like object): A file to load from.
			tag (bool): True to start from the beginning of this tag.
				False to skip tag_code and tag_length.
		
		Returns:
			self: If data were loaded successfully.
			None: Otherwise.

		'''

		if tag:
			code_and_length = struct.unpack('<H', f.read(2))[0]
			self.tag_length = code_and_length & 0b111111
			self.tag_code = code_and_length >> 6
			if self.tag_length >= 63:
				self.tag_length = struct.unpack('<I', f.read(4))[0]
		self._deserialize(f)
		return self

	def _deserialize(self, f):
		'''To be overridden by subclasses to deserialize their data.'''
		pass

	def serialize(self, f, tag=True):
		'''Writes this tag into a file-like object.

		Args:
			f (file-like object): A file to write to.
			tag (bool): True to also write tag_code and tag_length before
				writing tag data.
		
		'''

		if not tag:
			self._serialize(f)
			return
		
		data = StringIO()
		self._serialize(data)
		data = data.getvalue()

		self.tag_length = len(data)
		code_and_length = self.tag_code << 6
		if self.tag_length < 63:
			code_and_length |= self.tag_length
			f.write(struct.pack('<H', code_and_length))
		else:
			code_and_length |= 63
			f.write(struct.pack('<HI', code_and_length, self.tag_length))
		f.write(data)
	
	def _serialize(self, f):
		'''To be overridden by subclasses to serialize their data.'''
		pass


class UnknownTag(Tag):
	'''Unknown tag.'''

	def __init__(self):
		self.data = ''
	
	def _deserialize(self, f):
		self.data = ensure_read(f, self.tag_length)

	def _serialize(self, f):
		f.write(self.data)


class SetBackgroundColorTag(Tag):
	'''SetBackgroundColor tag.

	Attributes:
		background_color (RgbColor): The background color.
	
	'''

	def __init__(self):
		self.tag_code = SET_BACKGROUND_COLOR
		self.background_color = RgbColor()
	
	def _serialize(self, f):
		self.background_color.serialize(f)
	
	def _deserialize(self, f):
		self.background_color.deserialize(f)


class ClipEventFlags(SwfObject):
	'''Represents CLIPEVENTFLAGS structure.'''

	def __init__(self):
		self.key_up = False
		self.key_down = False
		self.mouse_up = False
		self.mouse_down = False
		self.mouse_move = False
		self.unload = False
		self.enter_frame = False
		self.load = False
		self.drag_over = False
		self.roll_out = False
		self.roll_over = False
		self.release_outside = False
		self.release = False
		self.press = False
		self.initialize = False
		self.data = False
		self.construct = False
		self.key_press = False
		self.drag_out = False
	
	def deserialize(self, f):
		br = BitReader(f)
		self.key_up = br.unsign_read(1)
		self.key_down = br.unsign_read(1)
		self.mouse_up = br.unsign_read(1)
		self.mouse_down = br.unsign_read(1)
		self.mouse_move = br.unsign_read(1)
		self.unload = br.unsign_read(1)
		self.enter_frame = br.unsign_read(1)
		self.load = br.unsign_read(1)
		self.drag_over = br.unsign_read(1)
		self.roll_out = br.unsign_read(1)
		self.roll_over = br.unsign_read(1)
		self.release_outside = br.unsign_read(1)
		self.release = br.unsign_read(1)
		self.press = br.unsign_read(1)
		self.initialize = br.unsign_read(1)
		self.data = br.unsign_read(1)
		t = br.unsign_read(5)
		if t:
			raise CorruptedSwfException('Reserved must be 0')
		self.construct = br.unsign_read(1)
		self.key_press = br.unsign_read(1)
		self.drag_out = br.unsign_read(1)
		t = br.unsign_read(8)
		if t:
			raise CorruptedSwfException('Reserved must be 0')
		return self
	
	def serialize(self, f):
		bw = BitWriter(f)
		bw.write(1, self.key_up)
		bw.write(1, self.key_down)
		bw.write(1, self.mouse_up)
		bw.write(1, self.mouse_down)
		bw.write(1, self.mouse_move)
		bw.write(1, self.unload)
		bw.write(1, self.enter_frame)
		bw.write(1, self.load)
		bw.write(1, self.drag_over)
		bw.write(1, self.roll_out)
		bw.write(1, self.roll_over)
		bw.write(1, self.release_outside)
		bw.write(1, self.release)
		bw.write(1, self.press)
		bw.write(1, self.initialize)
		bw.write(1, self.data)
		bw.write(5, 0)
		bw.write(1, self.construct)
		bw.write(1, self.key_press)
		bw.write(1, self.drag_out)
		bw.write(8, 0)
		bw.flush()


class ActionRecord(SwfObject):
	'''Represents ACTIONRECORD structure.

	TODO XXX: This class needs subclassed. action_data may be removed.

	Attributes:
		action_code (int): Action code.
		action_length (int): If action code is greater or equal than 0x80,
			this field is the length of payload.
		action_data (string): The payload.
	
	'''

	def __init__(self):
		self.action_code = 0
		self.action_length = 0
		self.action_data = None

	def deserialize(self, f):
		self.action_code = struct.unpack('B', f.read(1))[0]
		if self.action_code >= 0x80:
			self.action_length = struct.unpack('<H', f.read(1))[0]
			self.action_data = f.read(self.action_length)
		return self
	
	def serialize(self, f):
		if self.action_code >= 0x80:
			f.write(struct.pack('<BH', self.action_code, self.action_length))
			f.write(self.action_data)
		else:
			f.write(struct.pack('B', self.action_code))


class ClipActionRecord(SwfObject):
	'''Represents CLIPACTIONRECORD structure.'''

	def __init__(self):
		self.event_flags = ClipEventFlags()
		self.record_size = 0
		self.key_code = 0
		self.actions = []
	
	def deserialize(self, f):
		self.event_flags = ClipEventFlags().deserialize(f)
		self.record_size = struct.unpack('<I', f.read(4))[0]
		if self.event_flags.key_press:
			self.key_code = struct.unpack('B', f.read(1))[0]
			size = 1
		else:
			size = 0
		self.actions = []
		while size < self.record_size:
			action = ActionRecord().deserialize(f)
			size += 1
			if action.action_code >= 0x80:
				size += action.action_length + 2
			self.actions.append(action)
		return self
	
	def serialize(self, f):
		self.event_flags.serialize(f)
		data = StringIO()
		for action in self.actions:
			action.serialize(data)
		data = data.getvalue()
		size += len(data)
		if self.event_flags.key_press:
			size += 1
			f.write(struct.pack('<IB', size, self.key_code))
		else:
			f.write(struct.pack('<I', size))
		f.write(data)


class ClipActions(SwfObject):
	'''Represents CLIPACTIONS structure.

	TODO XXX: deserialize needs f.seek().

	Attributes:
		event_flags (ClipEventFlags): Events used in these clip actions.
		records (ClipActionRecord): Individual event handlers
	
	'''

	def __init__(self):
		self.event_flags = ClipEventFlags()
		self.records = []

	def deserialize(self, f):
		t = f.read(2)
		if t != b'\x00\x00':
			raise CorruptedSwfException('Reserved must be 0.')
		self.event_flags = ClipEventFlags().deserialize(f)
		self.records = []
		while True:
			look_ahead = f.read(4)
			if look_ahead == '\x00\x00\x00\x00':
				break
			f.seek(-4)
			action_record = ClipActionRecord().deserialize(f)
			self.records.append(action_record)
		return self
	
	def serialize(self, f):
		f.write('\x00\x00')
		self.event_flags.serialize(f)
		for action in self.actions:
			action.serialize(f)
		f.write('\x00\x00\x00\x00')


class PlaceObject2Tag(Tag):
	'''PlaceObject2 tag.

	We use None for attributes' initial value to determine if they are there.

	'''

	def __init__(self):
		self.tag_code = PLACE_OBJECT_2
		self.depth = 0
		self.move = 0
		self.character_id = None
		self.matrix = None
		self.color_transform = None
		self.ratio = None
		self.name = None
		self.clip_depth = None
		self.clip_actions = None
	
	def _deserialize(self, f):
		br = BitReader(f)
		has_clip_actions = br.unsign_read(1)
		has_clip_depth = br.unsign_read(1)
		has_name = br.unsign_read(1)
		has_ratio = br.unsign_read(1)
		has_color_trans = br.unsign_read(1)
		has_matrix = br.unsign_read(1)
		has_char = br.unsign_read(1)
		self.move = br.unsign_read(1)

		self.depth = struct.unpack('<H', f.read(2))[0]
		if has_char:
			self.character_id = struct.unpack('<H', f.read(2))[0]
		if has_matrix:
			self.matrix = Matrix().deserialize(f)
		if has_color_trans:
			self.color_transform = ColorTransformWithAlpha().deserialize(f)
		if has_ratio:
			self.ratio = struct.unpack('<H', f.read(2))[0]
		if has_name:
			self.name = String().deserialize(f)
		if has_clip_depth:
			self.clip_depth = struct.unpack('<H', f.read(2))[0]
		if has_clip_actions:
			self.clip_actions = ClipActions().deserialize(f)

	def _serialize(self, f):
		bits = [0] * 8
		for idx, name in enumerate(('clip_actions', 'clip_depth', 'name',
			'ratio', 'color_transform', 'matrix', 'character_id')):
			if self.__dict__.get(name, None) is not None:
				bits[idx] = 1
		bits[7] = self.move
		bw = BitWriter(f)
		for bit in bits:
			bw.write(1, bit)
		bw.flush()
		f.write(struct.pack('<H', self.depth))
		if self.character_id is not None:
			f.write(struct.pack('<H', self.character_id))
		if self.matrix is not None:
			self.matrix.serialize(f)
		if self.color_transform is not None:
			self.color_transform.serialize(f)
		if self.ratio is not None:
			f.write(struct.pack('<H', self.ratio))
		if self.name is not None:
			self.name.serialize(f)
		if self.clip_depth is not None:
			f.write(struct.pack('<H', self.clip_depth))
		if self.clip_actions is not None:
			self.clip_actions.serialize(f)


class SoundStreamHeadTag(Tag):
	'''SoundStreamHead tag.

	Attributes:
		reserved (int): Always 0.
		playback_sound_rate (int):
			0: 5.5 kHz
			1: 11 kHz
			2: 22 kHz
			3: 44 kHz
		playback_sound_size (int): Always 1 (16 bit).
		playback_sound_type (int): Either SND_MONO or SND_STEREO.
		stream_sound_compression (int): Either SND_ADPCM or SND_MP3.
			SND_MP3 is supported from SWF v4.
		stream_sound_rate (int):
			0: 5.5 kHz
			1: 11 kHz
			2: 22 kHz
			3: 44 kHz
		stream_sound_size (int): Always 1 (16 bit).
		stream_sound_type (int): Either SND_MONO or SND_STEREO.
		stream_sound_sample_count (int): Average number of samples.
		latency_seek (int): Number of samples to skip.
	
	'''

	def __init__(self):
		self.tag_code = SOUND_STREAM_HEAD
		self.reserved = 0
		self.playback_sound_rate = 0
		self.playback_sound_size = 0
		self.playback_sound_type = 0
		self.stream_sound_compression = 0
		self.stream_sound_rate = 0
		self.stream_sound_size = 0
		self.stream_sound_type = 0
		self.stream_sound_sample_count = 0
		self.latency_seek = 0
	
	def _deserialize(self, f):
		br = BitReader(f)
		# ignore 4 bits
		br.read(4)
		self.playback_sound_rate = br.unsign_read(2)
		self.playback_sound_size = br.unsign_read(1)
		if self.playback_sound_size != 1:
			raise CorruptedSwfException('Playback sound size is always 1')
		self.playback_sound_type = br.unsign_read(1)
		self.stream_sound_compression = br.unsign_read(4)
		if self.stream_sound_compression not in (SND_ADPCM, SND_MP3):
			raise CorruptedSwfException('Stream sound compression')
		self.stream_sound_rate = br.unsign_read(2)
		self.stream_sound_size = br.unsign_read(1)
		if self.stream_sound_size != 1:
			raise CorruptedSwfException('Stream sound size is always 1')
		self.stream_sound_type = br.unsign_read(1)
		self.stream_sound_sample_count = struct.unpack('<H', f.read(2))[0]
		if self.stream_sound_compression == SND_MP3 and self.tag_length > 4:
			self.latency_seek = struct.unpack('<h', f.read(2))[0]
	
	def _serialize(self, f):
		bw = BitWriter(f)
		bw.write(4, 0)
		bw.write(2, self.playback_sound_rate)
		bw.write(1, self.playback_sound_size)
		bw.write(1, self.playback_sound_type)
		bw.write(4, self.stream_sound_compression)
		bw.write(2, self.stream_sound_rate)
		bw.write(1, self.stream_sound_size)
		bw.write(1, self.stream_sound_type)
		bw.flush()
		if self.stream_sound_compression == SND_MP3 and self.latency_seek:
			f.write(struct.pack('<Hh', self.stream_sound_sample_count,
				self.latency_seek))
		else:
			f.write(struct.pack('<H', self.stream_sound_sample_count))


class SoundStreamBlockTag(Tag):
	'''Represents a SoundStreamBlock.

	TODO XXX: This tag needs broken down to precise sound data block.

	Attributes:
		sound_data (bytestring): Compressed sound data.
	
	'''

	def __init__(self):
		self.tag_code = SOUND_STREAM_BLOCK
		self.sound_data = b''
	
	def _serialize(self, f):
		f.write(self.sound_data)
	
	def _deserialize(self, f):
		self.sound_data = f.read(self.tag_length)


class ScreenVideoBlock(SwfObject):
	'''Represents a block in a Screen Video frame.

	Attributes:
		width (int): The block width.
		height (int): The block height.
		pixels (sequence of BgrColor): The pixels arranged from bottom left
			to top right.
	
	'''

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
	'''Represents SCREENVIDEOPACKET according to SWF spec.

	Attributes:
		frame_type (int): Either KEY_FRAME or INTER_FRAME.
		codec_id (int): 3 for SCREEN_VIDEO_CODEC.
		block_width (int): The block width, multiple of 16.
		block_height (int): The block height, multiple of 16.
		image_width (int): The frame width.
		image_height (int): The frame height.
		hoz_blk_cnt (int): Number of blocks in a row.
		ver_blk_cnt (int): Number of blocks in a column.
		block_count (int): Number of blocks.
		image_blocks (sequence of ScreenVideoBlock): The pixel data.
	
	'''

	class BgrColor(SwfObject):
		'''Represents a BGR color.

		Attributes:
			b (int): Blue component.
			g (int): Green component.
			r (int): Red component.
		
		'''

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
	
	def serialize(self, f):
		bw = BitWriter(f)
		bw.write(4, self.frame_type)
		bw.write(4, self.codec_id)
		bw.write(4, self.block_width // 16 - 1)
		bw.write(12, self.image_width)
		bw.write(4, self.block_height // 16 - 1)
		bw.write(12, self.image_height)
		bw.flush()
		data = StringIO()
		for blk in self.image_blocks:
			if blk:
				blk.serialize(data)
			else:
				data.write('\x00\x00')
		f.write(data.getvalue())

	def prepare_blocks(self):
		'''Initializes this object's image_blocks.'''

		self.hoz_blk_cnt = (self.image_width + self.block_width - 1) // \
			self.block_width
		self.ver_blk_cnt = (self.image_height + self.block_height - 1) // \
			self.block_height
		self.block_count = self.hoz_blk_cnt * self.ver_blk_cnt
		self.image_blocks = [None] * self.block_count

	def get_block_dimension(self, block_nr):
		'''Returns a block's width and height.

		Args:
			block_nr (int): The block number, zero-indexed. The
				first block is at lower left corner.
		
		Returns:
			width, height (tuple): The width and height.

		'''

		row = block_nr // self.hoz_blk_cnt
		col = block_nr % self.hoz_blk_cnt
		width = self.block_width if col < self.hoz_blk_cnt - 1 else \
			self.image_width - col * self.block_width
		height = self.block_height if row < self.ver_blk_cnt - 1 else \
			self.image_height - row * self.block_height
		return width, height

	def fill_blocks(self, f):
		'''Populates this object's image_blocks with pixel data from f.
		
		Args:
			f (file-like object): A file to read from.
		
		'''

		block_nr = 0
		while block_nr < self.block_count:
			width, height = self.get_block_dimension(block_nr)
			svb = ScreenVideoBlock(width, height).deserialize(f)
			self.image_blocks[block_nr] = svb
			block_nr += 1

	def to_image(self, image):
		'''Dumps pixels to an image.

		Args:
			image (Image): An RGB image.
		
		Returns:
			image: The same passed in image.
		
		'''

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
		'''Grabs pixel data from an image.

		If there is a previous_frame, unchanged block will be set to None.

		Args:
			img (Image): An image to grab pixels from.
			previous_frame (ScreenVideoPacket): The previous frame.
		
		'''

		block_nr = 0
		while block_nr < self.block_count:
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
			while idx >= 0:
				for pix in pixels[idx : idx + width]:
					pixel = ScreenVideoPacket.BgrColor()
					pixel.from_rgb_tuple(pix)
					svb.pixels.append(pixel)
				idx -= width

			# check if this block and the previous one is the same
			# if it is, we do not need this block
			if previous_frame and \
				previous_frame.image_blocks[block_nr] == svb:
				svb = None
			self.image_blocks[block_nr] = svb
			block_nr += 1

	def __repr__(self):
		return '%s%r' % (type(self).__name__, (
			self.image_width, self.image_height))


class VideoFrameTag(Tag):
	'''Represents VideoFrame tag.

	Attributes:
		stream_id (int): The stream this frame belongs to.
		frame_num (int): The frame number in that stream.
		video_data (bytestring): Frame data in encoded form.
	
	'''

	def __init__(self):
		self.tag_code = VIDEO_FRAME
		self.stream_id = 0
		self.frame_num = 0
		self.video_data = b''
	
	def _deserialize(self, f):
		if self.tag_length < 4:
			raise CorruptedSwfException()
		self.stream_id, self.frame_num = struct.unpack('<HH', f.read(4))
		self.video_data = ensure_read(f, self.tag_length - 4)

	def _serialize(self, f):
		# note that user must fix self.tag_length themselves before
		# calling serialize().
		f.write(struct.pack('<HH', self.stream_id, self.frame_num))
		f.write(self.video_data)


class SwfFile(SwfObject):
	'''An SWF file.

	This object is best used as an iterator. For example, to iterate
	through all tags in the SWF file::

		for tag in swf_file.iter_body():
			# do something with tag
	
	To save this object to file::

		swf_file.save('filename.swf', swf_file.iter_body())
	
	To save a compressed file, make sure the file header version is set
	to at least 6, and its compressed attribute to True::

		swf_file.header.file_header.compressed = True
		swf_file.header.file_header.version = 7
		swf_file.save(...)
	
	After an iteration completes, it cannot rewind. The list of tags
	can be saved to support multiple iterations.

	Attributes:
		header (Header): Both FileHeader and FrameHeader.
		body (list of Tag): All tags. This attribute may not present.
			See method `load`.
	
	'''

	decoders = {
		SET_BACKGROUND_COLOR: SetBackgroundColorTag,
		PLACE_OBJECT_2: PlaceObject2Tag,
		SOUND_STREAM_HEAD: SoundStreamHeadTag,
		SOUND_STREAM_BLOCK: SoundStreamBlockTag,
		VIDEO_FRAME: VideoFrameTag,
	}

	def __init__(self, file_name=None):
		'''Constructs an SwfFile object.

		If file_name is not None, the file will be loaded. If the file
		is compressed, its content will be decompressed fully in memory,
		the original file is then closed. If the file is not compressed,
		only the header is read, the file is not closed.

		Args:
			file_name (string): A file to load from.
		
		'''

		self.header = None
		self.file = None
		if file_name:
			self.load_header(file_name)

	def close(self):
		'''Close the underlying file object.'''

		self.file.close()
	
	def __del__(self):
		if self.file:
			self.file.close()

	def load_header(self, file_name):
		'''Reads in SWF header record.

		If this SWF file is compressed, the whole file content will be
		read and decompressed into memory, the underlying file is closed.

		Args:
			file_name (string): The SWF file to be loaded.
		
		Raises:
			SwfException: If file is compressed but version is less
				than 6.
		
		'''

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
		'''Reads in header and, optionally, the body.

		Args:
			file_name (string): A file to read from.
			body (bool): True to populate self.body.
		
		'''

		self.load_header(file_name)
		if body:
			self.body = [tag for tag in self.iter_body()]

	def iter_body(self):
		'''Returns an iterator through all tags, including the END tag.'''

		last_tag = None
		while True:
			try:
				tag = Tag().deserialize(self.file)
			except struct.error:
				if last_tag and last_tag.tag_code == 0:
					break
				raise CorruptedSwfException()
			clz = SwfFile.decoders.get(tag.tag_code, UnknownTag)
			tag = clz().clone_tag(tag).deserialize(self.file, False)
			yield tag
			last_tag = tag
	
	def save(self, file_name, iter_body=None):
		'''Saves self to a SWF file.

		The file_length field in SWF header will be fixed accordingly.

		Args:
			file_name (string): A file to write to. This file will be
				overwritten.
			iter_body (iterator): An iterator of Tag objects. If this
				is None, the current object's body attribute is used.
		
		Raises:
			SwfException: If iter_body is None and self.body is not set.
		
		'''

		if not iter_body:
			if 'body' not in self.__dict__:
				raise SwfException('File body is required')
			iter_body = self.body
		
		fio = StringIO()
		self.header.frame_header.serialize(fio)
		for tag in iter_body:
			tag.serialize(fio)
		data = fio.getvalue()
		self.header.file_header.file_length = 8 + len(data)
		if self.header.file_header.compressed:
			data = zlib.compress(data)
		
		f = open(file_name, 'wb')
		try:
			self.header.file_header.serialize(f)
			f.write(data)
		finally:
			f.close()
