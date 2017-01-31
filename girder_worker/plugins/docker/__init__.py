import docker


def before_run(e):
    import executor
    if e.info['task']['mode'] == 'docker':
        executor.validate_task_outputs(e.info['task_outputs'])


def cleanup(e):
    """
    Since files written by docker containers are owned by root, we can't
    clean them up in the worker process since that typically doesn't run
    as root. So, we run a lightweight container to make the temp dir cleanable.
    """
    from .executor import DATA_VOLUME
    if e.info['task']['mode'] == 'docker' and '_tempdir' in e.info['kwargs']:
        tmpdir = e.info['kwargs']['_tempdir']

        client = docker.from_env()
        config = {
            'tty': True,
            'volumes': {
                tmpdir: {
                    'bind': DATA_VOLUME,
                    'mode': 'rw'
                }
            },
            'detach': False,
            'remove': True
        }
        args = ['chmod', '-R', 'a+rw', DATA_VOLUME]

        try:
            client.containers.run('busybox', args, **config)
        except:
            print('Error setting perms on docker tempdir %s.' % tmpdir)
            raise


def load(params):
    from girder_worker.core import events, register_executor
    import executor

    events.bind('run.before', params['name'], before_run)
    events.bind('run.finally', params['name'], cleanup)
    register_executor('docker', executor.run)
