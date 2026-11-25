import os
from PIL import Image, ImageDraw

def create_app_icon(output_png, output_ico):
    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    size = (256, 256)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw rounded dark glass rectangle background
    draw.rounded_rectangle([8, 8, 248, 248], radius=56, fill=(15, 23, 42, 235), outline=(56, 189, 248, 220), width=6)

    # Circle accent
    draw.ellipse([48, 48, 208, 208], fill=(56, 189, 248, 45))
    
    # Aesthetic music equalizer bars
    draw.rounded_rectangle([72, 120, 88, 188], radius=8, fill=(56, 189, 248, 255))
    draw.rounded_rectangle([104, 80, 120, 188], radius=8, fill=(244, 63, 94, 255))
    draw.rounded_rectangle([136, 100, 152, 188], radius=8, fill=(16, 185, 129, 255))
    draw.rounded_rectangle([168, 132, 184, 188], radius=8, fill=(245, 158, 11, 255))

    img.save(output_png, "PNG")
    img.save(output_ico, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"Generated PNG icon at: {output_png}")
    print(f"Generated ICO icon at: {output_ico}")

if __name__ == "__main__":
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    png_path = os.path.join(assets_dir, "app_icon.png")
    ico_path = os.path.join(assets_dir, "app_icon.ico")
    create_app_icon(png_path, ico_path)
