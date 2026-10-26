"""Local regression tests; run: python -m unittest -v test_normalize_exam_pdfs

Only pypdf and the Python standard library are required. No student files or
API credentials are read. Synthetic PDFs are created in memory/temp folders.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                           NameObject, NumberObject, RectangleObject)
import normalize_exam_pdfs as tool


def scan_pdf(rotation=0, media=(0, 0, 200, 300), crop=None,
             image=(0, 0, 200, 300), prefix=b"", annotations=False, userunit=1):
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=300)
    page.mediabox = RectangleObject(media)
    if crop is not None:
        page.cropbox = RectangleObject(crop)
    page.rotation = rotation
    page[NameObject('/UserUnit')] = NumberObject(userunit)
    pixels = DecodedStreamObject()
    # Deliberately asymmetric pixels to expose incorrect rotation in render tests.
    pixels.set_data(bytes((255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255)))
    pixels.update({NameObject('/Type'): NameObject('/XObject'),
                   NameObject('/Subtype'): NameObject('/Image'),
                   NameObject('/Width'): NumberObject(2),
                   NameObject('/Height'): NumberObject(2),
                   NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
                   NameObject('/BitsPerComponent'): NumberObject(8)})
    image_ref = writer._add_object(pixels.flate_encode())
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/XObject'): DictionaryObject({NameObject('/Scan'): image_ref})})
    x0, y0, x1, y1 = image
    stream = DecodedStreamObject()
    stream.set_data(prefix + f'q 1 0 0 1 {x0} {y0} cm {x1-x0} 0 0 {y1-y0} 0 0 cm /Scan Do Q\n'.encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    if annotations:
        page[NameObject('/Annots')] = ArrayObject([writer._add_object(DictionaryObject({
            NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Text'),
            NameObject('/Rect'): RectangleObject((10, 10, 20, 20))}))])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class GeometryTests(unittest.TestCase):
    def test_clean_copy_is_byte_identical(self):
        data = scan_pdf()
        output, info = tool.normalize_data(data)
        self.assertEqual(data, output)
        self.assertTrue(info['byte_identical_copy'])
        self.assertEqual(info['after']['pages_needing_attention'], [])

    def test_all_rotations(self):
        for angle in (90, 180, 270, 360, 450, -90):
            with self.subTest(angle=angle):
                output, info = tool.normalize_data(scan_pdf(rotation=angle))
                page = PdfReader(io.BytesIO(output)).pages[0]
                self.assertEqual(page.rotation, 0)
                expected = [300, 200] if angle % 360 in (90, 270) else [200, 300]
                for a, b in zip(info['after']['pages'][0]['displayed_media_size_points'], expected):
                    self.assertAlmostEqual(a, b)
                self.assertTrue(info['encoded_image_streams_unchanged'])
                self.assertEqual(info['after']['pages_needing_attention'], [])

    def test_inherited_rotation(self):
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(scan_pdf())))
        page = writer.pages[0]
        del page[NameObject('/Rotate')]
        parent = page['/Parent']
        parent[NameObject('/Rotate')] = NumberObject(270)
        out = io.BytesIO(); writer.write(out)
        output, info = tool.normalize_data(out.getvalue())
        self.assertEqual(PdfReader(io.BytesIO(output)).pages[0].rotation, 0)
        self.assertAlmostEqual(info['after']['pages'][0]['displayed_media_size_points'][0], 300)

    def test_nonzero_and_negative_origins(self):
        for x, y in ((10, 20), (-10, -20)):
            data = scan_pdf(media=(x, y, 200+x, 300+y), image=(x, y, 200+x, 300+y))
            _, info = tool.normalize_data(data)
            self.assertEqual(info['after']['pages_needing_attention'], [])
            self.assertTrue(tool.close_box(info['after']['pages'][0]['media_box_pdf_points'], [0, 0, 200, 300]))

    def test_scan_overhang_detected_and_not_silently_removed(self):
        data = scan_pdf(image=(3.06, 1.68, 206.78, 298.32))
        output, info = tool.normalize_data(data)
        self.assertEqual(output, data)
        self.assertIn('scan_extends_outside_mediabox', info['after']['pages'][0]['issues'])
        self.assertAlmostEqual(info['after']['pages'][0]['simple_scan']['outside_media_points']['right'], 6.78)

    def test_full_scan_expands_canvas_without_resampling(self):
        output, info = tool.normalize_data(scan_pdf(image=(3.06, 1.68, 206.78, 298.32)), full_scan=True)
        self.assertTrue(info['encoded_image_streams_unchanged'])
        self.assertEqual(info['after']['pages_needing_attention'], [])
        self.assertTrue(tool.close_box(info['after']['pages'][0]['media_box_pdf_points'], [0, 0, 206.78, 300]))
        again, info2 = tool.normalize_data(output, full_scan=True)
        self.assertEqual(again, output)
        self.assertEqual(info2['changes'], [])

    def test_rotation_and_expansion_together(self):
        _, info = tool.normalize_data(scan_pdf(rotation=270, image=(-5, -7, 205, 310)), full_scan=True)
        self.assertTrue(tool.close_box(info['after']['pages'][0]['media_box_pdf_points'], [0, 0, 317, 210]))
        self.assertEqual(info['after']['pages_needing_attention'], [])

    def test_crop_preserved_unless_requested(self):
        data = scan_pdf(crop=(10, 20, 190, 280))
        output, _ = tool.normalize_data(data)
        self.assertEqual(output, data)
        _, info = tool.normalize_data(data, full_scan=True)
        self.assertEqual(info['after']['pages_needing_attention'], [])

    def test_complex_content_not_blindly_uncropped(self):
        data = scan_pdf(prefix=b'0 0 200 200 re W n\n', crop=(10, 10, 190, 290))
        with self.assertRaisesRegex(ValueError, 'not recognized'):
            tool.normalize_data(data, full_scan=True)

    def test_annotations_block_rewrite(self):
        with self.assertRaisesRegex(ValueError, 'annotations'):
            tool.normalize_data(scan_pdf(annotations=True, rotation=90))

    def test_userunit_requires_review(self):
        with self.assertRaisesRegex(ValueError, 'UserUnit'):
            tool.normalize_data(scan_pdf(userunit=2))

    def test_encrypted_pdf_refused(self):
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(scan_pdf())))
        writer.encrypt('test-password')
        out = io.BytesIO(); writer.write(out)
        with self.assertRaisesRegex(ValueError, 'encrypted'):
            tool.normalize_data(out.getvalue())

    def test_atomic_write_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'file.pdf'
            path.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                tool.write_new_atomic(path, b'replacement')
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_cli_accepts_exam3_and_check_creates_no_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'Exam3.pdf'
            source.write_bytes(scan_pdf(rotation=90))
            with contextlib.redirect_stdout(io.StringIO()):
                code = tool.main(['--check', str(source), '--output-dir', str(root / 'output')])
            self.assertEqual(code, 2)
            self.assertFalse((root / 'output').exists())
            with contextlib.redirect_stdout(io.StringIO()):
                code = tool.main([str(source), '--output-dir', str(root / 'output')])
            self.assertEqual(code, 0)
            self.assertTrue((root / 'output' / 'Exam3.pdf').is_file())
            self.assertEqual(PdfReader(source).pages[0].rotation, 90)


if __name__ == '__main__':
    unittest.main()
