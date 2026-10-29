"""Actual embedded document references, not guessed filenames or viewer execution."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'))
import kaoyan_on_demand as tool
from kaoyan_public_http import safe_url,SafeStop
import test_kaoyan_on_demand as fixture
URL,page=fixture.URL,fixture.page

class EmbeddedDocuments(unittest.TestCase):
 def links(self,markup,year=2026,layer='lines'):
  info={};links=tool.discover_links(page(markup),URL,year,layer,diagnostics=info);return links,info
 def test_direct_frames_objects_and_embeds_are_discovered_without_running_viewer(self):
  links,_=self.links('<iframe src="/a.pdf"></iframe><object data="/b.pdf" type="application/pdf"></object><embed src="/c.png">')
  self.assertEqual(links,['https://fixture.edu.cn/a.pdf','https://fixture.edu.cn/b.pdf','https://fixture.edu.cn/c.png'])
 def test_object_uses_its_resource_data_attribute_not_an_unrelated_src(self):
  links,_=self.links('<object src="/ignored.pdf" data="/actual.pdf" type="application/pdf"></object>')
  self.assertEqual(links,['https://fixture.edu.cn/actual.pdf'])
 def test_empty_resource_attribute_never_reuses_the_parent_as_a_document(self):
  links,info=self.links('<object src="/ignored.pdf" data="" type="application/pdf"></object><iframe src=" "></iframe>')
  self.assertEqual(links,[]);self.assertEqual([r['reason']for r in info['embedded_issues']],['empty_reference','empty_reference'])
 def test_known_viewer_file_is_extracted_and_unicode_path_is_encoded(self):
  links,_=self.links('<iframe src="/front/ofdview/ofdview1.html?file=https://fixture.edu.cn/file/%E5%88%86%E6%95%B0.pdf"></iframe>')
  self.assertEqual(links,['https://fixture.edu.cn/file/%E5%88%86%E6%95%B0.pdf'])
 def test_relative_file_uses_viewer_url_and_same_site_base(self):
  links,_=self.links('<base href="/docs/"><iframe src="viewer.html?file=./score.pdf"></iframe>')
  self.assertEqual(links,['https://fixture.edu.cn/docs/score.pdf'])
 def test_incomplete_percent_url_is_a_document_gap_not_a_guessed_file(self):
  links,info=self.links('<iframe src="/front/ofdview/ofdview1.html?file=/file/notice%E"></iframe>')
  self.assertEqual(links,[]);self.assertEqual(info['embedded_issues'][0]['reason'],'incomplete_uri')
  with self.assertRaises(SafeStop):safe_url('https://fixture.edu.cn/file/notice%E')
 def test_unsupported_ambiguous_private_login_and_cross_site_references_are_not_followed(self):
  values=['/unknown.html?file=/a.pdf','/viewer.html?file=/a.pdf&amp;file=/b.pdf','/viewer.html?file=https://other.edu.cn/a.pdf','/viewer.html?file=http://127.0.0.1/a.pdf','/viewer.html?file=/signin.aspx/a.pdf','/viewer.html?file=/a.pdf%3Fname%3DAlice','javascript:open("/a.pdf")']
  for value in values:
   with self.subTest(value=value):self.assertEqual(self.links('<iframe src="'+value+'"></iframe>')[0],[])
 def test_encoded_login_is_rejected_but_encoded_literal_percent_is_valid(self):
  for url in ['https://fixture.edu.cn/%6Cogin/a.pdf','https://fixture.edu.cn/%256cogin/a.pdf']:
   with self.assertRaises(SafeStop):safe_url(url)
  url='https://fixture.edu.cn/file/rate20%25.pdf';self.assertEqual(safe_url(url),url)
  self.assertEqual(self.links('<iframe src="/viewer.html?file=/file/rate20%2525.pdf"></iframe>')[0],[url])
 def test_wrong_year_or_business_parent_and_external_base_are_not_authority(self):
  self.assertEqual(self.links('<iframe src="/a.pdf"></iframe>',2025)[0],[])
  self.assertEqual(self.links('<iframe src="/a.pdf"></iframe>',2026,'catalog')[0],[])
  self.assertEqual(self.links('<base href="https://other.edu.cn/"><iframe src="/a.pdf"></iframe>')[0],[])
 def test_roster_filename_is_not_retrieved_in_a_line_request(self):
  self.assertEqual(self.links('<iframe src="/2026拟录取名单.pdf"></iframe>')[0],[])
 def test_anchor_and_article_image_use_the_declared_same_site_base(self):
  markup='<base href="/official/"><a href="cutoff.pdf">2026复试分数线</a><article><img src="line.png"></article>'
  self.assertEqual(self.links(markup)[0],['https://fixture.edu.cn/official/cutoff.pdf','https://fixture.edu.cn/official/line.png'])
 def test_unknown_base_does_not_guess_relative_business_links(self):
  markup='<base href="https://other.edu.cn/"><a href="cutoff.pdf">2026复试分数线</a><a href="https://fixture.edu.cn/absolute.pdf">2026复试分数线</a>'
  self.assertEqual(self.links(markup)[0],['https://fixture.edu.cn/absolute.pdf'])
 def test_navigation_resolves_declared_base_without_guessing_root_paths(self):
  body=page('<base href="/official/"><a href="graduate/">合成大学研究生院</a>')
  self.assertEqual(tool.navigation_links(body,URL,'合成大学',{'school_homepage_url':'https://fixture.edu.cn/'}),['https://fixture.edu.cn/official/graduate/'])
 def test_embedded_original_is_not_crowded_out_by_navigation(self):
  html=''.join('<a href="/2026-line-'+str(i)+'.html">2026复试分数线</a>'for i in range(15))+'<iframe src="/a.pdf"></iframe>'
  links,_=self.links(html);self.assertEqual(len(links),12);self.assertEqual(links[0],'https://fixture.edu.cn/a.pdf')

class EmbeddedOrchestration(unittest.TestCase):
 setUp=fixture.OnDemandTests.setUp
 tearDown=fixture.OnDemandTests.tearDown
 cells=fixture.OnDemandTests.cells
 run_fake=fixture.OnDemandTests.run_fake
 def test_valid_embedded_reference_reaches_normal_independent_reader(self):
  body=page('<iframe src="/original.pdf"></iframe>');parsed=tool.parse_official_html(fixture.line_page(),URL,{'name':'合成大学','institution_id':'4100000001'},2026,'lines',['0854'])
  fetch=Mock(side_effect=[({'body':body},{'url':URL,'http_status':200}),({'body':b'%PDF-test'},{'url':'https://fixture.edu.cn/original.pdf','http_status':200})])
  from unittest.mock import patch
  with patch.object(tool,'parse_official_document',return_value=parsed)as reader:
   result,_,publisher=self.run_fake(fetch=fetch)
  self.assertTrue(result['published']);self.assertEqual(reader.call_count,1);self.assertEqual(publisher.call_count,1)
 def test_bad_embed_is_reported_without_requesting_its_broken_address(self):
  fetch=Mock(return_value=({'body':page('<iframe src="/viewer.html?file=/missing%E"></iframe>')},{'url':URL,'http_status':200}))
  result,_,publisher=self.run_fake(fetch=fetch);self.assertEqual(fetch.call_count,1);publisher.assert_not_called();self.assertIn('嵌入原件地址不完整',result['outcomes'][0]['reason'])

if __name__=='__main__':unittest.main()
