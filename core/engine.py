import os, struct, json, shutil, zipfile, subprocess
import zstandard as zstd
from PIL import Image
import texture2ddecoder
from sc_compression import Decompressor

GL_MAP = {
    0x93B0: ("ASTC_4x4", 4, 4), 0x93B1: ("ASTC_5x4", 5, 4), 0x93B2: ("ASTC_5x5", 5, 5),
    0x93B3: ("ASTC_6x5", 6, 5), 0x93B4: ("ASTC_6x6", 6, 6), 0x93B5: ("ASTC_8x5", 8, 5),
    0x93B6: ("ASTC_8x6", 8, 6), 0x93B7: ("ASTC_8x8", 8, 8), 0x93B8: ("ASTC_10x5", 10, 5),
    0x93B9: ("ASTC_10x6", 10, 6), 0x93BA: ("ASTC_10x8", 10, 8), 0x93BB: ("ASTC_10x10", 10, 10),
    0x9278: ("ETC2", 0, 0), 0x8D64: ("ETC1", 0, 0), 0x8058: ("RGBA8", 0, 0)
}

class Engine:
    def decode_file(self, file_path, filename, progress_callback=None):
        base_dir = os.path.dirname(file_path)
        clean_name = filename.rsplit('.', 1)[0]
        work_dir = os.path.join(base_dir, clean_name + "_extracted")
        if os.path.exists(work_dir): shutil.rmtree(work_dir)
        os.makedirs(work_dir)

        if progress_callback: progress_callback("Декомпрессия контейнера...", 10)
        with open(file_path, "rb") as f: raw_data = f.read()

        decompressed_data = raw_data
        sig = "RAW"
        zstd_pos = raw_data.find(b'\x28\xb5\x2f\xfd')
        header_data = b""

        if zstd_pos != -1:
            sig = "SCTX_ZSTD"
            header_data = raw_data[:zstd_pos]
            try:
                decompressed_data = zstd.ZstdDecompressor().decompress(raw_data[zstd_pos:], max_output_size=200_000_000)
            except: pass
        else:
            try:
                decompressed_data = Decompressor().decompress(raw_data)
                sig = "SC_LZMA"
            except: pass

        offsets = []
        last = 0
        while True:
            p = decompressed_data.find(b'\xABKTX 11\xBB\r\n\x1A\n', last)
            if p == -1: break
            offsets.append(p)
            last = p + 12

        layout = {"filename": filename, "signature": sig, "has_header": len(header_data) > 0, "textures": []}
        with open(os.path.join(work_dir, "base_dump.bin"), "wb") as f: f.write(decompressed_data)
        if header_data:
            with open(os.path.join(work_dir, "header.bin"), "wb") as f: f.write(header_data)

        if not offsets and sig == "SCTX_ZSTD":
            configs = [(1024, 1024, 8, 8, "ASTC_8x8_RAW"), (1024, 1024, 4, 4, "ASTC_4x4_RAW")]
            for w, h, bw, bh, fmt_name in configs:
                req_size = (w * h * 16) // (bw * bh)
                if len(decompressed_data) >= req_size:
                    try:
                        dec = texture2ddecoder.decode_astc(decompressed_data[:req_size], w, h, bw, bh)
                        img = Image.frombytes('RGBA', (w, h), dec, 'raw', 'BGRA')
                        tex_name = f"texture_0_{w}x{h}.png"
                        img.save(os.path.join(work_dir, tex_name))
                        layout["textures"].append({"index": 0, "name": tex_name, "offset_start": 0, "offset_end": req_size, "width": w, "height": h, "format": fmt_name})
                        break
                    except: pass
        else:
            offsets.append(len(decompressed_data))
            total_tex = len(offsets) - 1
            for i in range(total_tex):
                if progress_callback: progress_callback(f"Декодирование текстуры {i+1}/{total_tex}...", 20 + int((i / total_tex) * 70))
                s, e = offsets[i], offsets[i+1]
                chunk = decompressed_data[s:e]
                try:
                    gl = struct.unpack('<I', chunk[28:32])[0]
                    w = struct.unpack('<I', chunk[36:40])[0]
                    h = struct.unpack('<I', chunk[40:44])[0]
                    kv = struct.unpack('<I', chunk[60:64])[0]
                    tex_data = chunk[64+kv+4:]
                    fmt_info = GL_MAP.get(gl)
                    if not fmt_info: continue
                    fmt_name, bw, bh = fmt_info
                    
                    if "ASTC" in fmt_name:
                        dec = texture2ddecoder.decode_astc(tex_data, w, h, bw, bh)
                        img = Image.frombytes('RGBA', (w, h), dec, 'raw', 'BGRA')
                    elif "ETC2" in fmt_name:
                        dec = texture2ddecoder.decode_etc2a8(tex_data, w, h)
                        img = Image.frombytes('RGBA', (w, h), dec, 'raw', 'BGRA')
                    elif "ETC1" in fmt_name:
                        dec = texture2ddecoder.decode_etc1(tex_data, w, h)
                        img = Image.frombytes('RGBA', (w, h), dec, 'raw', 'BGRA')
                    elif "RGBA8" in fmt_name:
                        img = Image.frombytes('RGBA', (w, h), tex_data, 'raw', 'RGBA')

                    nm = f"texture_{i}.png"
                    img.save(os.path.join(work_dir, nm))
                    layout["textures"].append({"index": i, "name": nm, "offset_start": s, "offset_end": e, "width": w, "height": h, "format": fmt_name})
                except: pass

        if progress_callback: progress_callback("Создание ZIP...", 95)
        with open(os.path.join(work_dir, "layout.json"), "w") as f: json.dump(layout, f, indent=4)
        zip_path = os.path.join(base_dir, f"{filename}.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for root, _, files in os.walk(work_dir):
                for file in files: zf.write(os.path.join(root, file), file)
        return zip_path

    def encode_file(self, zip_path, progress_callback=None):
        base_dir = os.path.dirname(zip_path)
        work_dir = os.path.join(base_dir, "encode_work")
        if os.path.exists(work_dir): shutil.rmtree(work_dir)
        os.makedirs(work_dir)

        with zipfile.ZipFile(zip_path, 'r') as zf: zf.extractall(work_dir)
        with open(os.path.join(work_dir, "layout.json"), "r") as f: layout = json.load(f)

        base_path = os.path.join(work_dir, "base_dump.bin")
        with open(base_path, "rb") as f: base_data = bytearray(f.read())

        total_tex = len(layout["textures"])
        for i, tex in enumerate(layout["textures"]):
            if progress_callback: progress_callback(f"Компрессия {tex['name']}...", 10 + int((i / total_tex) * 80))
            png_path = os.path.join(work_dir, tex["name"])
            if not os.path.exists(png_path): continue

            if "ASTC" in tex["format"]:
                astc_out = os.path.join(work_dir, "temp.astc")
                blk = "8x8" if "8x8" in tex["format"] else "4x4"
                try:
                    subprocess.run(["astcenc", "-cl", png_path, astc_out, blk, "-medium"], stdout=subprocess.DEVNULL, check=True)
                    with open(astc_out, "rb") as f: raw_astc = f.read()[16:]
                    if "RAW" in tex["format"]:
                        if total_tex == 1: base_data = raw_astc
                    else:
                        s = tex["offset_start"]
                        kv_len = struct.unpack('<I', base_data[s+60:s+64])[0]
                        data_start = s + 64 + kv_len + 4
                        base_data[data_start : data_start + len(raw_astc)] = raw_astc
                except: pass

        if progress_callback: progress_callback("Финальная сборка...", 95)
        if layout["signature"] == "SCTX_ZSTD":
            compressed = zstd.ZstdCompressor(level=3).compress(base_data)
            header_path = os.path.join(work_dir, "header.bin")
            final_data = open(header_path, "rb").read() + compressed if os.path.exists(header_path) else compressed
        else:
            final_data = base_data

        out_path = os.path.join(base_dir, "encoded_" + layout["filename"])
        with open(out_path, "wb") as f: f.write(final_data)
        return out_path
