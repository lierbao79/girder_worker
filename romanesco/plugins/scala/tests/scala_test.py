import os
import romanesco
import shutil
import unittest

_cwd = _tmp = None


def setUpModule():
    global _tmp
    global _cwd
    _cwd = os.getcwd()
    _tmp = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'tmp', 'scala')
    if not os.path.isdir(_tmp):
        os.makedirs(_tmp)
    os.chdir(_tmp)


def tearDownModule():
    os.chdir(_cwd)
    if os.path.isdir(_tmp):
        shutil.rmtree(_tmp)


class TestScalaMode(unittest.TestCase):
    def testScalaMode(self):
        task = {
            'mode': 'scala',
            'script': """
val message = "Hello, " + foo + "!"
val square = x * x
val not_b = !b
val bufferedSource = io.Source.fromFile(file)
for (line <- bufferedSource.getLines) {
    val cols = line.split(",").map(_.trim)
    println(s"${cols(0)}|${cols(1)}|${cols(2)}")
}
""",
            'inputs': [
                {
                    'id': 'foo',
                    'format': 'text',
                    'type': 'string'
                },
                {
                    'id': 'x',
                    'format': 'number',
                    'type': 'number'
                },
                {
                    'id': 'file',
                    'type': 'string',
                    'format': 'text',
                    'target': 'filepath'
                },
                {
                    'id': 'b',
                    'format': 'boolean',
                    'type': 'boolean'
                }
            ],
            'outputs': [
                {
                    'id': '_stdout',
                    'format': 'text',
                    'type': 'string'
                },
                {
                    'id': 'message',
                    'format': 'text',
                    'type': 'string'
                },
                {
                    'id': 'square',
                    'format': 'number',
                    'type': 'number'
                },
                {
                    'id': 'not_b',
                    'format': 'boolean',
                    'type': 'boolean'
                }
            ]
        }

        inputs = {
            'foo': {
                'format': 'text',
                'data': 'world'
            },
            'file': {
                'format': 'text',
                'data': 'a,  b, c\n1,\t2,3\n'
            },
            'x': {
                'format': 'number',
                'data': 12
            },
            'b': {
                'format': 'boolean',
                'data': True
            }
        }

        out = romanesco.run(task, inputs=inputs)

        self.assertEqual(out, {
            '_stdout': {
                'data': 'a|b|c\n1|2|3\n',
                'format': 'text'
            },
            'message': {
                'data': 'Hello, world!',
                'format': 'text'
            },
            'square': {
                'data': 144,
                'format': 'number'
            },
            'not_b': {
                'data': False,
                'format': 'boolean'
            }
        })
