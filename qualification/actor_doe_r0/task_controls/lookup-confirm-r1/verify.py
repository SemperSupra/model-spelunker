"""Independent fixed expected-output oracle for public synthetic control."""
import pathlib,sys,tempfile
EXPECTED="VALUE=confirm-selected-23\n"
def verify(root):
    path=root/"value.txt"
    return path.is_file() and path.read_text(encoding="utf-8")==EXPECTED
if __name__=="__main__":
    if sys.argv[1]=="--self-test":
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);(p/"value.txt").write_text(EXPECTED,encoding="utf-8");assert verify(p)
            (p/"value.txt").write_text("WRONG\n",encoding="utf-8");assert not verify(p)
        print("PASS independent positive/negative verifier controls")
    else:
        ok=verify(pathlib.Path(sys.argv[1]));print("PASS" if ok else "FAIL");sys.exit(0 if ok else 1)
