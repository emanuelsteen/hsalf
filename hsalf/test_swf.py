import swf
import unittest
from cStringIO import StringIO


class BitReaderTest(unittest.TestCase):

	def test_unsigned_read(self):
		#data = '0010 1000 1100 0001'
		data = StringIO(b'\x28\xC1')
		br = swf.BitReader(data)
		self.assertEqual(0, br.unsign_read(1))
		self.assertEqual(1, br.unsign_read(2))
		self.assertEqual(2, br.unsign_read(3))
		self.assertEqual(3, br.unsign_read(4))
		self.assertEqual(0, br.unsign_read(5))
		self.assertEqual(1, br.unsign_read(1))
		self.assertRaises(swf.IoSwfException, br.unsign_read, 1)

	def test_signed_read(self):
		# data = '00 01 10 11'
		data = StringIO(b'\x1B')
		br = swf.BitReader(data)
		self.assertRaises(ValueError, br.sign_read, 0)
		self.assertRaises(ValueError, br.sign_read, 1)
		self.assertEqual(0, br.sign_read(2))
		self.assertEqual(1, br.sign_read(2))
		self.assertEqual(-2, br.sign_read(2))
		self.assertEqual(-1, br.sign_read(2))
		self.assertRaises(swf.IoSwfException, br.sign_read, 2)


class BitWriterTest(unittest.TestCase):

	def test_required_bits(self):
		self.assertEqual(2, swf.BitWriter.required_bits(1))
		self.assertEqual(2, swf.BitWriter.required_bits(0))
		self.assertEqual(3, swf.BitWriter.required_bits(2))
		self.assertEqual(2, swf.BitWriter.required_bits(-1))
		self.assertEqual(2, swf.BitWriter.required_bits(-2))
		self.assertEqual(3, swf.BitWriter.required_bits(-3))
		self.assertEqual(3, swf.BitWriter.required_bits(0, 1, 2, 3,
			-1, -2))
		self.assertEqual(3, swf.BitWriter.required_bits(0, 1, 2, 3,
			-1, -2, -3, -4))
		self.assertEqual(4, swf.BitWriter.required_bits(0, 1, 2, 3, 4,
			-1, -2, -3, -4, -5))

	def test_unsigned_write(self):
		f = StringIO()
		br = swf.BitWriter(f)
		br.write(1, 0)
		br.write(2, 1)
		br.write(3, 2)
		br.write(4, 3)
		br.write(5, 0)
		br.write(1, 1)
		br.flush()
		self.assertEqual(b'\x28\xC1', f.getvalue())

	def test_signed_write(self):
		f = StringIO()
		br = swf.BitWriter(f)
		br.write(2, 0)
		br.write(2, 1)
		br.write(2, -2)
		br.write(2, -1)
		br.flush()
		self.assertEqual(b'\x1B', f.getvalue())
	
	def test_zero_pad(self):
		f = StringIO()
		br = swf.BitWriter(f)
		br.write(7, 1)
		br.flush()
		self.assertEqual(b'\x02', f.getvalue())
	
if __name__ == '__main__':
	unittest.main()
