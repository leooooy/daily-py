
from daily_py import FileHandler

fh = FileHandler(base_path="/path/to/你的根目录")


res = fh.batch_rename_recursive(r"D:\ftp\1225\xgame\FaceSwap\test",
                                "cgibsonCreatorProfilevertCivitai16",
                                "CgibsonCreatorProfilevertCivitai16",
                                use_regex=False,
                                include_dirs=False,
                                dry_run=False)
print(res)
