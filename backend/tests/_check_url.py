from pathlib import Path
import urllib.parse as p

pp = Path('D:/tools/netops/backend/templates/simhei.ttf')
print('Path:', repr(pp))
print('Path str:', repr(str(pp)))
r1 = p.urlparse(str(pp))
print('urlparse(str):', r1.scheme, '|', r1.path)

# Try Path.as_uri()
print('as_uri:', pp.as_uri())
r2 = p.urlparse(pp.as_uri())
print('urlparse(as_uri):', r2.scheme, '|', r2.path)

# Pass Path object directly
r3 = p.urlparse(pp)  # type: ignore
print('urlparse(Path):', r3)
