"""This module defines tasks executed in the pipeline."""

import json
from collections import OrderedDict
import six

from gaia.core.base import GaiaObject
from gaia.core.port import Port


class Task(GaiaObject):

    """Defines a pipeline element.

    A task is an element of the pipeline responsible for completing an
    atomic task given one or more inputs and pushing the result to the
    next task or tasks.
    """

    def __init__(self, spec={}, **kw):
        """Initialize an abstract task."""
        spec = spec.copy()
        spec['inputs'] = spec.get('inputs', [])[:]
        spec['outputs'] = spec.get('outputs', [])[:]

        self._spec = spec

        #: Input connection mapping
        self._inputs = self._port_dict(spec['inputs'])

        #: Output connection mapping
        self._outputs = self._port_dict(spec['outputs'])

        #: data cache
        self._input_data = {}
        self._output_data = {}

    @property
    def spec(self):
        """Return the spec object for the task."""
        return self._spec

    def __str__(self):
        """Serialize the task as a json object."""
        return json.dumps(self.spec)

    @staticmethod
    def _port_dict(ports):
        """Generate an ordered dict from a list of port specs."""
        o = OrderedDict()
        for port_spec in ports:
            port = Port(port_spec)
            o[port.name] = port
        return o

    @property
    def inputs(self):
        """Return the dictionary of input ports."""
        return self._inputs

    @property
    def outputs(self):
        """Return the dictionary of output ports."""
        return self._outputs

    def set_input(self, *arg, **kw):
        """Bind (and cache) data to input ports.

        Positional arguments map to input ports numbered as '0', '1', etc.
        Keyword arguments set inputs by name.

        Example task:
        >>> def run(s, a=a, b=b):
        ...     return s + ':' + str(a + b)
        >>> spec = {
        ...     'input_ports': [
        ...         {'name': '0', 'type': 'string', 'format': 'text'},
        ...         {'name': 'a', 'type': 'number', 'format': 'number'},
        ...         {'name': 'b', 'type': 'number', 'format': 'number'},
        ...     ]
        ...     'output_ports': [
        ...         {'name': '0', 'type': 'string', 'format': 'text'}
        ...     ],
        ...     'function': run
        ... }
        >>> t1 = Task(spec)
        >>> t2 = Task(spec)

        # Input set from data sources
        >>> t1.set_input('The sum', a=2, b=3).get_output()
        'The sum:5'

        # Input set from port objects
        >>> t2.set_input(t1.get_output(), a=4, b=5).get_output()
        'The sum:5:9'
        """
        # Convert arguments into keyword arguments
        for i, a in enumerate(arg):
            kw[str(i)] = a

        for name, value in six.iteritems(kw):
            if name not in self._inputs:
                raise ValueError("Invalid port name '{0}'".format(name))

            data = None
            if isinstance(value, dict):
                try:
                    data = self.inputs[name].fetch(value)
                except:
                    pass

            if data is None:
                data = value

            self._dirty = True
        return self

    def get_input(self, name='0'):
        """Return the data bound to the given input port.

        :param str name: An input port name
        :rtype: object or None
        """
        return self._input_data.get(name)

    def get_output(self, name='0'):
        """Return the data bound to the given output port.

        :param str name: An input port name
        :rtype: object or None
        """
        if name not in self._outputs:
            raise ValueError("Invalid port name '{0}'".format(name))
        if self.dirty:
            self.run()
        return self._output_data.get(name)

    def run(self, *arg, **kw):
        """Execute the task.

        This method requires at a minimum that all input ports are connected
        to valid data sources.  Subclasses can customize the execution with
        keyword arguments.  The reference implementation only checks that
        the input ports are all connected and raises an error if they
        aren't.
        """
        self.dirty = False

    def _reset(self, *args):
        """Set dirty state for the task."""
        self.dirty = True

    def _reset_downstream(self, _, isdirty, *args):
        """Set dirty state on all downstream tasks."""
        if isdirty and not self.dirty:
            self._reset()


Task.add_property(
    'dirty',
    doc='Stores the current cache state of the Task',
    default=True,
    on_change=Task._reset_downstream
)
