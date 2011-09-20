# Copyright (C) 2011 Associated Universities, Inc. Washington DC, USA.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
# 
# Correspondence concerning GBT software should be addressed as follows:
#	GBT Operations
#	National Radio Astronomy Observatory
#	P. O. Box 2
#	Green Bank, WV 24944-0002 USA

"""This module provides a serial interface to the Valon 5007 synthesizer."""

# Python modules
import struct
# Third party modules
import serial


__author__ = "Patrick Brandt"
__copyright__ = "Copyright 2011, Associated Universities, Inc."
__credits__ = ["Patrick Brandt, Stewart Rumley, Steven Stark"]
__license__ = "GPL"
#__version__ = "1.0"
__maintainer__ = "Patrick Brandt"


# Handy aliases
SYNTH_A = 0x00
SYNTH_B = 0x08

INT_REF = 0x00
EXT_REF = 0x01

ACK = 0x06
NACK = 0x15

class Synthesizer:
    def __init__(self, port):
        self.conn = serial.Serial(None, 9600, serial.EIGHTBITS,
                                  serial.PARITY_NONE, serial.STOPBITS_ONE)
        self.conn.setPort(port)

    def _generate_checksum(self, bytes):
        return chr(sum([ord(b) for b in bytes]) % 256)

    def _verify_checksum(self, bytes, checksum):
        return (self._generate_checksum(bytes) == checksum)

    def _pack_freq_registers(self, ncount, frac, mod, dbf, old_bytes):
        dbf_table = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4}
        reg0, reg1, reg2, reg3, reg4, reg5 = struct.unpack('>IIIIII', old_bytes)
        reg0 &= 0x80000007
        reg0 |= ((ncount & 0xffff) << 15) | ((frac & 0x0fff) << 3)
        reg1 &= 0xffff8007
        reg1 |= (mod & 0x0fff) << 3
        reg4 &= 0xff8fffff
        reg4 |= (dbf_table.get(dbf, 0)) << 20
        return struct.pack('>IIIIII', reg0, reg1, reg2, reg3, reg4, reg5)

    def _unpack_freq_registers(self, bytes):
        dbf_rev_table = {0: 1, 1: 2, 2: 4, 3: 8, 4: 16}
        reg0, reg1, reg2, reg3, reg4, reg5 = struct.unpack('>IIIIII', bytes)
        ncount = (reg0 >> 15) & 0xffff
        frac = (reg0 >> 3) & 0x0fff
        mod = (reg1 >> 3) & 0x0fff
        dbf = dbf_rev_table[(reg4 >> 20) & 0x07]
        return ncount, frac, mod, dbf

    def get_frequency(self, synth):
        """Returns the current output frequency for the selected synthesizer."""
        self.conn.open()
        bytes = struct.pack('>B', 0x80 | synth)
        self.conn.write(bytes)
        bytes = self.conn.read(24)
        checksum = self.conn.read(1)
        self.conn.close()
        #self._verify_checksum(bytes, checksum)
        ncount, frac, mod, dbf = self._unpack_freq_registers(bytes)
        EPDF = self._getEPDF(synth)
        return (ncount + float(frac) / mod) * EPDF / dbf

    def set_frequency(self, synth, freq, chan_spacing = 10.):
        min, max = self.get_vco_range(synth)
        dbf = 1
        while (freq * dbf) <= min and dbf <= 16:
            dbf *= 2
        if dbf > 16:
            dbf = 16
        vco = freq * dbf
        EPDF = self._getEPDF(synth)
        ncount = int(vco / EPDF)
        frac = int((vco - ncount * float(EPDF)) / chan_spacing + 0.5)
        mod = int(EPDF / float(chan_spacing) + 0.5)
        if frac != 0 and mod != 0:
            while not (frac & 1) and not (mod & 1):
                frac /= 2
                mod /= 2
        else:
            frac = 0
            mod = 1
        self.conn.open()
        bytes = struct.pack('>B', 0x80 | synth)
        self.conn.write(bytes)
        old_bytes = self.conn.read(24)
        checksum = self.conn.read(1)
        #self._verify_checksum(old_bytes, checksum)
        bytes = struct.pack('>B24s', 0x00 | synth, self._pack_freq_registers(ncount, frac, mod, dbf, old_bytes))
        checksum = self._generate_checksum(bytes)
        self.conn.write(bytes + checksum)
        bytes = self.conn.read(1)
        self.conn.close()
        ack = struct.unpack('>B', bytes)[0]
        return ack == ACK

    def get_reference(self):
        self.conn.open()
        bytes = struct.pack('>B', 0x81)
        self.conn.write(bytes)
        bytes = self.conn.read(4)
        checksum = self.conn.read(1)
        self.conn.close()
        #self._verify_checksum(bytes, checksum)
        freq = struct.unpack('>I', bytes)[0]
        return freq

    def set_reference(self, freq):
        self.conn.open()
        bytes = struct.pack('>BI', 0x01, freq)
        checksum = self._generate_checksum(bytes)
        self.conn.write(bytes + checksum)
        bytes = self.conn.read(1)
        self.conn.close()
        ack = struct.unpack('>B', bytes)[0]
        return ack == ACK

    def get_options(self, synth):
        self.conn.open()
        bytes = struct.pack('>B', 0x80 | synth)
        self.conn.write(bytes)
        bytes = self.conn.read(24)
        checksum = self.conn.read(1)
        self.conn.close()
        #self._verify_checksum(bytes, checksum)
        reg0, reg1, reg2, reg3, reg4, reg5 = struct.unpack('>IIIIII', bytes)
        low_spur = ((reg2 >> 30) & 1) & ((reg2 >> 29) & 1)
        double = (reg2 >> 25) & 1
        half = (reg2 >> 24) & 1
        r = (reg2 >> 14) & 0x03ff
        return double, half, r, low_spur

    def set_options(self, synth, double = 0, half = 0, r = 1, low_spur = 0):
        self.conn.open()
        bytes = struct.pack('>B', 0x80 | synth)
        self.conn.write(bytes)
        bytes = self.conn.read(24)
        checksum = self.conn.read(1)
        #self._verify_checksum(bytes, checksum)
        reg0, reg1, reg2, reg3, reg4, reg5 = struct.unpack('>IIIIII', bytes)
        reg2 &= 0x9c003fff
        reg2 |= (((low_spur & 1) << 30) | ((low_spur & 1) << 29) | 
                 ((double & 1) << 25) | ((half & 1) << 24) |
                 ((r & 0x03ff) << 14))
        bytes = struct.pack('>BIIIIII', 0x00 | synth,
                            reg0, reg1, reg2, reg3, reg4, reg5)
        checksum = self._generate_checksum(bytes)
        self.conn.write(bytes + checksum)
        bytes = self.conn.read(1)
        self.conn.close()
        ack = struct.unpack('>B', bytes)[0]
        return ack == ACK

    def get_ref_select(self):
        """Returns the currently selected reference clock.

        Returns 1 if the external reference is selected, 0 otherwise.
        """
        self.conn.open()
        bytes = struct.pack('>B', 0x86)
        self.conn.write(bytes)
        bytes = self.conn.read(1)
        checksum = self.conn.read(1)
        self.conn.close()
        #self._verify_checksum(bytes, checksum)
        is_ext = struct.unpack('>B', bytes)[0]
        return is_ext & 1

    def set_ref_select(self, e_not_i = 1):
        """Selects either internal or external reference clock.

        Parameters:
            e_not_i -- 1 (external) or 0 (internal)
        """
        self.conn.open()
        bytes = struct.pack('>Bc', 0x06, e_not_i & 1)
        checksum = self._generate_checksum(bytes)
        self.conn.write(bytes + checksum)
        bytes = self.conn.read(1)
        self.conn.close()
        ack = struct.unpack('>B', bytes)[0]
        return ack == ACK

    def get_vco_range(self, synth):
        self.conn.open()
        bytes = struct.pack('>B', 0x83 | synth)
        self.conn.write(bytes)
        bytes = self.conn.read(4)
        checksum = self.conn.read(1)
        self.conn.close()
        #self._verify_checksum(bytes, checksum)
        min, max = struct.unpack('>HH', bytes)
        return min, max

    def set_vco_range(self, synth, min, max):
        self.conn.open()
        bytes = struct.pack('>BHH', 0x03 | synth, min, max)
        checksum = self._generate_checksum(bytes)
        self.conn.write(bytes + checksum)
        bytes = self.conn.read(1)
        self.conn.close()
        ack = struct.unpack('>B', bytes)[0]
        return ack == ACK

    def get_phase_lock(self, synth):
        self.conn.open()
        bytes = struct.pack('>B', 0x86 | synth)
        self.conn.write(bytes)
        bytes = self.conn.read(1)
        checksum = self.conn.read(1)
        self.conn.close()
        #self._verify_checksum(bytes, checksum)
        mask = (synth << 1) or 0x20
        lock = struct.unpack('>B', bytes)[0] & mask
        return lock > 0

    def get_label(self, synth):
        self.conn.open()
        bytes = struct.pack('>B', 0x82 | synth)
        self.conn.write(bytes)
        bytes = self.conn.read(16)
        checksum = self.conn.read(1)
        self.conn.close()
        #self._verify_checksum(bytes, checksum)
        return bytes

    def set_label(self, synth, label):
        self.conn.open()
        bytes = struct.pack('>B16s', 0x02 | synth, label)
        checksum = self._generate_checksum(bytes)
        self.conn.write(bytes + checksum)
        bytes = self.conn.read(1)
        self.conn.close()
        ack = struct.unpack('>B', bytes)[0]
        return ack == ACK

    def flash(self):
        self.conn.open()
        bytes = struct.pack('>B', 0x40)
        checksum = self._generate_checksum(bytes)
        self.conn.write(bytes + checksum)
        bytes = self.read(1)
        self.conn.close()
        ack = struct.unpack('>B', bytes)[0]
        return ack == ACK

    def _getEPDF(self, synth):
        reference = self.get_reference() / 1e6
        double, half, r, low_spur = self.get_options(synth)
        if(double): reference *= 2.0
        if(half):   reference /= 2.0
        if(r > 1):  reference /= r
        return reference
