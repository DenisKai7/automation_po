from pathlib import Path
import re
import shutil
from typing import Literal

Category = Literal["Success", "Rejected", "Failed"]


class FileArchiver:
    CATEGORIES: tuple[Category, ...] = ("Success", "Rejected", "Failed")

    def __init__(self, processed_dir: Path | str):
        self.processed_dir = Path(processed_dir)
        for cat in self.CATEGORIES:
            (self.processed_dir / cat).mkdir(parents=True, exist_ok=True)

    def archive(self, source_path: Path | str, category: Category, move: bool = False, overwrite: bool = True) -> Path:
        src = Path(source_path)
        if not src.exists():
            return src

        target_folder = self.processed_dir / category
        target_path = target_folder / src.name

        # Clean existing copies from other categories to maintain single source of truth
        for other_cat in self.CATEGORIES:
            if other_cat != category:
                other_file = self.processed_dir / other_cat / src.name
                if other_file.exists():
                    try:
                        other_file.unlink()
                    except OSError:
                        pass

        if not overwrite and target_path.exists():
            stem = src.stem
            suffix = src.suffix
            counter = 1
            while target_path.exists():
                target_path = target_folder / f"{stem}_{counter}{suffix}"
                counter += 1

        if move:
            # Overwrite if target already exists
            if target_path.exists():
                target_path.unlink()
            shutil.move(str(src), str(target_path))
        else:
            shutil.copy2(str(src), str(target_path))

        return target_path

    def cleanup_duplicates(self) -> int:
        """Removes existing duplicate files with '_1', '_2' suffixes created in prior runs."""
        removed = 0
        suffix_pattern = re.compile(r"^(.+)_\d+(\.[a-zA-Z0-9]+)$")

        for cat in self.CATEGORIES:
            cat_folder = self.processed_dir / cat
            if not cat_folder.exists():
                continue

            for file in cat_folder.iterdir():
                if not file.is_file():
                    continue
                m = suffix_pattern.match(file.name)
                if m:
                    base_name = f"{m.group(1)}{m.group(2)}"
                    base_file = cat_folder / base_name
                    # If base file exists, this is a redundant numbered duplicate
                    if base_file.exists():
                        try:
                            file.unlink()
                            removed += 1
                        except OSError:
                            pass
        return removed
