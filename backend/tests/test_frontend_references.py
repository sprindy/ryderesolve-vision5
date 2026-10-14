import unittest
from html.parser import HTMLParser
from pathlib import Path

FRONT=Path(__file__).resolve().parents[2]/'frontend'
class References(HTMLParser):
    def __init__(self): super().__init__(); self.refs=[]
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key in ('href','src') and value: self.refs.append(value)

class ReferenceTest(unittest.TestCase):
    def test_every_local_html_reference_resolves(self):
        for page in FRONT.glob('*.html'):
            parser=References(); parser.feed(page.read_text(encoding='utf-8'))
            for ref in parser.refs:
                if ref.startswith(('http:','https:','#')): continue
                self.assertTrue(ref.startswith('./'),(page.name,ref))
                self.assertTrue((FRONT/ref[2:].split('?',1)[0]).is_file(),(page.name,ref))
    def test_api_configuration_loaded_before_client(self):
        for name in ('rider','driver','admin'):
            text=(FRONT/(name+'.html')).read_text(encoding='utf-8')
            self.assertLess(text.index('./config.js'),text.index('./common.js'))

if __name__=='__main__': unittest.main()
