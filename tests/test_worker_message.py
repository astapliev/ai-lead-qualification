import json
from pathlib import Path
import unittest

class WorkerMessageTests(unittest.TestCase):
    def test_html_length_review_and_bigint(self):
        workflow = json.loads((Path(__file__).parents[1] / 'n8n/worker.json').read_text())
        code = next(n for n in workflow['nodes'] if n['name'] == 'Prepare Manager Message')['parameters']['pythonCode']
        namespace = {}
        exec('def run(_items):\n' + '\n'.join('    ' + line for line in code.splitlines()), namespace)
        base = {'id': '9223372036854775000', 'name': '<Имя>', 'contact': 'Email: example@example.com',
                'message': '<&😀' * 2000, 'budget': None, 'request_id': 'test',
                'processing_token': '42', 'lead_status': 'needs_review', 'lead_score': None}
        output = namespace['run']([{'json': base}])[0]
        text = output['json']['manager_message']
        self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 4096)
        self.assertIn('&lt;Имя&gt;', text)
        self.assertIn('ручная проверка', text)
        self.assertNotIn('None/100', text)
        self.assertEqual(output['json']['id'], base['id'])
        self.assertEqual(output['json']['processing_token'], '42')
