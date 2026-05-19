import os
import shutil
from setuptools import setup

try:
    from Cython.Build import cythonize
except ImportError:
    print("Cython is not installed. Please run: pip install cython")
    exit(1)

def build():
    # 获取项目根目录
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    
    # 需要编译的核心安全文件
    from setuptools import Extension
    
    extensions = [
        Extension("backend.license_auth.verifier",  ["backend/license_auth/verifier.py"]),
        Extension("backend.license_auth.crypto",    ["backend/license_auth/crypto.py"]),
        Extension("backend.license_auth.middleware", ["backend/license_auth/middleware.py"]),
    ]
    
    # 清理已有的旧 .c 中间文件，强制 Cython 重新生成，防止缓存旧代码
    import glob
    for c_file in glob.glob(os.path.join(project_root, "backend/license_auth/*.c")):
        try:
            os.remove(c_file)
            print(f"已清理旧的 C 源码: {c_file}")
        except Exception:
            pass

    print("开始编译核心模块...")
    setup(
        ext_modules=cythonize(
            extensions,
            compiler_directives={'language_level': "3", 'always_allow_keywords': True}
        ),
        # --inplace 表示把编译生成的 .so 或 .pyd 文件放在原目录
        script_args=["build_ext", "--inplace"]
    )
    
    # 编译完成后，你可以选择自动删除原来的 .py 文件（源码）
    print("\n编译完成！生成的动态链接库已放在 backend/license_auth 目录下。")
    print("------------------------------------------------------")
    print("安全建议: 在最终发布部署前（例如 Docker 镜像打包环节），")
    print("可以通过加入以下代码将源码彻底删除：")
    for f in ["backend/license_auth/verifier.py", "backend/license_auth/crypto.py"]:
        print(f"os.remove('{f}')")
    print("------------------------------------------------------")

if __name__ == "__main__":
    build()
