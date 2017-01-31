import ConfigParser
import girder_worker
import httmock
import mock
import os
import shutil
import six
import stat
import sys
import unittest

from girder_worker.core import run, io, TaskSpecValidationError
from girder_worker.plugins.docker.executor import DATA_VOLUME

_tmp = None
OUT_FD, ERR_FD = 100, 200
_out = six.StringIO('output message\n')
_err = six.StringIO('error message\n')

stdout_socket_mock = mock.Mock()
stdout_socket_mock.fileno.return_value = OUT_FD

stderr_socket_mock = mock.Mock()
stderr_socket_mock.fileno.return_value = ERR_FD

docker_container_mock = mock.Mock()
docker_container_mock.attach_socket.side_effect = [stdout_socket_mock, stderr_socket_mock]

docker_client_mock = mock.Mock()
docker_client_mock.containers.run.return_value = docker_container_mock

process_mock = mock.Mock()
process_mock.configure_mock(**{
    'communicate.return_value': ('', ''),
    'poll.return_value': 0,
    'stdout.fileno.return_value': OUT_FD,
    'stderr.fileno.return_value': ERR_FD,
    'returncode': 0
})

def _reset_mocks():
    global docker_client_mock, docker_container_mock
    docker_client_mock.reset_mock()
    # Need to reset side_effect
    docker_container_mock.attach_socket.side_effect = [stdout_socket_mock, stderr_socket_mock]

# Monkey patch select.select in the docker task module
def _mockSelect(r, w, x, *args, **kwargs):
    return r, w, x
girder_worker.core.utils.select.select = _mockSelect


# Monkey patch os.read to simulate subprocess stdout and stderr
def _mockOsRead(fd, *args, **kwargs):
    global _out, _err
    if fd == OUT_FD:
        return _out.read()
    elif fd == ERR_FD:
        return _err.read()
girder_worker.plugins.docker.executor.os.read = _mockOsRead


def setUpModule():
    global _tmp
    _tmp = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'tmp', 'docker')
    girder_worker.config.set('girder_worker', 'tmp_root', _tmp)
    try:
        girder_worker.config.add_section('docker')
    except ConfigParser.DuplicateSectionError:
        pass

    if os.path.isdir(_tmp):
        shutil.rmtree(_tmp)


def tearDownModule():
    if os.path.isdir(_tmp):
        shutil.rmtree(_tmp)


class TestDockerMode(unittest.TestCase):
    def setUp(self):
        _reset_mocks()

    @mock.patch('subprocess.Popen')
    @mock.patch('docker.from_env')
    def testDockerMode(self, from_env, popen):
        popen.return_value = process_mock
        from_env.return_value = docker_client_mock

        task = {
            'mode': 'docker',
            'docker_image': 'test/test:latest',
            'container_args': [
                '-f', '$input{foo}', '--temp-dir=$input{_tempdir}',
                '$flag{bar}'
            ],
            'pull_image': True,
            'inputs': [{
                'id': 'foo',
                'name': 'A variable',
                'format': 'string',
                'type': 'string',
                'target': 'filepath'
            }, {
                'id': 'bar',
                'name': 'Bar',
                'format': 'boolean',
                'type': 'boolean',
                'arg': '--bar'
            }],
            'outputs': [{
                'id': '_stderr',
                'format': 'string',
                'type': 'string'
            }]
        }

        inputs = {
            'foo': {
                'mode': 'http',
                'url': 'https://foo.com/file.txt'
            },
            'bar': {
                'mode': 'inline',
                'data': True
            }
        }

        @httmock.all_requests
        def fetchMock(url, request):
            if url.netloc == 'foo.com' and url.scheme == 'https':
                return 'dummy file contents'
            else:
                raise Exception('Unexpected url ' + repr(url))

        with httmock.HTTMock(fetchMock):
            # Use user-specified filename
            _old = sys.stdout
            mockedStdOut = six.StringIO()
            sys.stdout = mockedStdOut
            out = run(
                task, inputs=inputs, cleanup=False, validate=False,
                auto_convert=False)
            sys.stdout = _old

            # We didn't specify _stdout as an output, so it should just get
            # printed to sys.stdout (which we mocked)
            lines = mockedStdOut.getvalue().splitlines()
            self.assertEqual(lines[0],
                             'Pulling Docker image: test/test:latest')
            self.assertEqual(lines[-2], 'output message')
            self.assertEqual(
                lines[-1], 'Garbage collecting old containers and images.')

            # We bound _stderr as a task output, so it should be in the output
            self.assertEqual(out, {
                '_stderr': {
                    'data': 'error message\n',
                    'format': 'string'
                }
            })

            # We should have one call to images.pull(...)
            self.assertEqual(docker_client_mock.images.pull.call_count, 1)
            self.assertEqual(docker_client_mock.images.pull.call_args_list[0][0], ('test/test:latest', ))


            # We should have two calls to containers.run(...)
            self.assertEqual(docker_client_mock.containers.run.call_count, 2)
            run1, run2 = docker_client_mock.containers.run.call_args_list


            args, kwargs = run1
            self.assertEqual(args[0], 'test/test:latest')
            six.assertRegex(self, kwargs['volumes'].keys()[0], _tmp + '/.*')
            self.assertEqual(kwargs['volumes'].itervalues().next()['bind'], DATA_VOLUME)
            self.assertEqual(args[1][0:2], ['-f', '%s/file.txt' % DATA_VOLUME])
            self.assertEqual(args[1][-2], '--temp-dir=%s' % DATA_VOLUME)
            self.assertEqual(args[1][-1], '--bar')

            # Call to docker-gc
            popen_calls = popen.call_args_list
            self.assertEqual(len(popen_calls), 1)
            six.assertRegex(self, popen_calls[0][1]['args'][0], 'docker-gc$')

            args, kwargs = run2
            self.assertEqual(args[0], 'busybox')

            self.assertTrue(kwargs['remove'])
            six.assertRegex(self, kwargs['volumes'].keys()[0], _tmp + '/.*')
            self.assertEqual(kwargs['volumes'].itervalues().next()['bind'], DATA_VOLUME)
            self.assertEqual(args[1], ['chmod', '-R', 'a+rw', DATA_VOLUME])

            # Make sure we can specify a custom entrypoint to the container
            _reset_mocks()

            task['entrypoint'] = '/bin/bash'

            inputs['foo'] = {
                'mode': 'http',
                'url': 'https://foo.com/file.txt'
            }
            inputs['bar'] = {
                'mode': 'inline',
                'data': False
            }
            run(task, inputs=inputs, validate=False, auto_convert=False)
            self.assertEqual(docker_client_mock.containers.run.call_count, 2)
            args, kwargs = docker_client_mock.containers.run.call_args_list[0]
            self.assertEqual(args[0], 'test/test:latest')
            self.assertEqual(kwargs['entrypoint'], ['/bin/bash'])

            self.assertNotIn('--bar', args)
            self.assertEqual(args[1][0:2], ['-f', '%s/file.txt' % DATA_VOLUME])

            _reset_mocks()
            popen.reset_mock()

            # Make sure custom config settings are respected
            girder_worker.config.set('docker', 'cache_timeout', '123456')
            girder_worker.config.set(
                'docker', 'exclude_images', 'test/test:latest')

            # Make sure we can skip pulling the image
            task['pull_image'] = False
            inputs['foo'] = {
                'mode': 'http',
                'url': 'https://foo.com/file.txt'
            }
            run(task, inputs=inputs, validate=False, auto_convert=False)
            # Assert no call to images.pull
            self.assertEqual(docker_client_mock.images.pull.call_count, 0)
            self.assertEqual(docker_client_mock.containers.run.call_count, 2)

            popen_calls = popen.call_args_list
            self.assertEqual(len(popen_calls), 1)
            six.assertRegex(self, popen_calls[0][1]['args'][0], 'docker-gc$')

            env = popen_calls[0][1]['env']
            self.assertEqual(env['GRACE_PERIOD_SECONDS'], '123456')
            six.assertRegex(self, env['EXCLUDE_FROM_GC'], 'docker_gc_scratch/.docker-gc-exclude$')

    @mock.patch('subprocess.Popen')
    @mock.patch('docker.from_env')
    def testOutputValidation(self, from_env, popen):
        popen.return_value = process_mock
        from_env.return_value = docker_client_mock

        task = {
            'mode': 'docker',
            'docker_image': 'test/test',
            'pull_image': True,
            'inputs': [],
            'outputs': [{
                'id': 'file_output_1',
                'format': 'text',
                'type': 'string'
            }]
        }

        msg = (r'^Docker outputs must be either "_stdout", "_stderr", or '
               'filepath-target outputs\.$')
        with self.assertRaisesRegexp(TaskSpecValidationError, msg):
            run(task)

        _reset_mocks()
        task['outputs'][0]['target'] = 'filepath'
        task['outputs'][0]['path'] = '/tmp/some/invalid/path'
        msg = (r'^Docker filepath output paths must either start with "%s/" '
               'or be specified relative to that directory\.$' % DATA_VOLUME)
        with self.assertRaisesRegexp(TaskSpecValidationError, msg):
            run(task)

        task['outputs'][0]['path'] = '%s/valid_path.txt' % DATA_VOLUME
        path = os.path.join(_tmp, '.*', 'valid_path\.txt')
        msg = r'^Output filepath %s does not exist\.$' % path
        with self.assertRaisesRegexp(Exception, msg):
            run(task)
        # Make sure docker stuff actually got called in this case.
        self.assertEqual(docker_client_mock.containers.run.call_count, 2)

        # Simulate a task that has written into the temp dir
        tmp = os.path.join(_tmp, 'simulated_output')
        if not os.path.isdir(tmp):
            os.makedirs(tmp)
        path = os.path.join(tmp, 'valid_path.txt')
        with open(path, 'w') as f:
            f.write('simulated output')
        _reset_mocks()
        outputs = run(task, _tempdir=tmp)
        self.assertEqual(outputs, {
            'file_output_1': {
                'data': path,
                'format': 'text'
            }
        })
        _reset_mocks()
        # If no path is specified, we should fall back to the input name
        del task['outputs'][0]['path']
        path = os.path.join(_tmp, '.*', 'file_output_1')
        msg = r'^Output filepath %s does not exist\.$' % path
        with self.assertRaisesRegexp(Exception, msg):
            run(task)

    @mock.patch('subprocess.Popen')
    @mock.patch('docker.from_env')
    def testNamedPipes(self, from_env, popen):
        popen.return_value = process_mock
        from_env.return_value = docker_client_mock

        task = {
            'mode': 'docker',
            'docker_image': 'test/test',
            'pull_image': False,
            'inputs': [],
            'outputs': [{
                'id': 'named_pipe',
                'format': 'text',
                'type': 'string',
                'target': 'filepath',
                'stream': True
            }]
        }

        outputs = {
            'named_pipe': {
                'mode': 'test_dummy'
            }
        }

        class DummyAdapter(girder_worker.core.utils.StreamPushAdapter):
            def write(self, buf):
                pass

        # Mock out the stream adapter
        io.register_stream_push_adapter('test_dummy', DummyAdapter)

        tmp = os.path.join(_tmp, 'testing')
        if not os.path.isdir(tmp):
            os.makedirs(tmp)

        run(task, inputs={}, outputs=outputs, _tempdir=tmp, cleanup=False)

        # Make sure pipe was created inside the temp dir
        pipe = os.path.join(tmp, 'named_pipe')
        self.assertTrue(os.path.exists(pipe))
        self.assertTrue(stat.S_ISFIFO(os.stat(pipe).st_mode))
