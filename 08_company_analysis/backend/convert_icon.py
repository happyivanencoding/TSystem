from PIL import Image
import os
import sys

def convert_to_ico(source_path, target_path):
    try:
        if not os.path.exists(source_path):
            print(f"Error: {source_path} not found.")
            return False
            
        img = Image.open(source_path)
        
        # Resize to standard icon sizes if needed, or just save as ICO containing multiple sizes
        # Windows icons usually have 16, 32, 48, 64, 128, 256
        icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
        
        img.save(target_path, format='ICO', sizes=icon_sizes)
        print(f"Successfully converted {source_path} to {target_path}")
        return True
    except Exception as e:
        print(f"Failed to convert icon: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        src = sys.argv[1]
    else:
        src = "icon.png"
        
    convert_to_ico(src, "app.ico")


