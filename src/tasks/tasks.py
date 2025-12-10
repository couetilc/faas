import threading
import networkx
import itertools


class TaskGroup:
    class Exception(Exception):
        pass

    class Dependency():
        # TODO: have two interfaces
        # Task(arg = TaskGroup.Dependency(task)) # stores all of task output in single variable
        # Task(arg = TaskGroup.Dependency(task, param)) # stores "param" of output in single variable
        # but what about a return value that isn't a dictionary? Like a single value, or a tuple?
        def __init__(self, task, param = None):
            self.task = task

    def __init__(self, *args):
        self.tasks = set(args)
        self.graph = networkx.DiGraph()
        # TODO: manage stdout and stderr for all child tasks.
        # TODO: create some kind of cancel Event, or perhaps a Queue.
        pass
    def __str__(self):
        # TODO: print the TaskGraph as a mermaid diagram representation.
        pass
    def start(self):
        for task in networkx.topological_sort(self.graph):
            task.start()
        # TODO: start each start task
        # TODO: store start time of task graph
        # TODO: store end time of task graph
        pass
    def cancel():
        # TODO: will cancel all tasks in the graph
        pass
    def wait(self):
        for task in self.tasks:
            task.wait()
    def set_stdout():
        # TODO: will set stdout file for task group
        pass
    def set_stderr():
        # TODO: will set stderr file for task group
        pass
    def poll():
        # TODO: returns true if still executing, false otherwise (I think this is the convention? I could ask AI for suggestion for this API)
        pass
    def add_precedence(self, *tasks):
        if len(tasks) < 2:
            raise TaskGroup.Exception(
                'TaskGroup.add_precedence called with fewer than two arguments. '
                'Precedence constraints must be expressed in terms of 2 or more tasks')
        # self.add_tasks(*tasks) # TODO: tasks can be added through add_precedence
        for i in range(len(tasks) - 1):
            self.graph.add_edge(tasks[i], tasks[i + 1])
        if exc := self.verify_constraints():
            for i in range(len(tasks) - 1):
                self.graph.remove_edge(tasks[i], tasks[i + 1])
            raise exc
    def add_tasks(self, *args):
        self.tasks.update(args)
        self.graph.add_nodes_from(args)
        edges = list()
        def check_dependency(arg):
            if isinstance(arg, TaskGroup.Dependency):
                if arg.task not in self.tasks:
                    raise TaskGroup.Exception(
                        'Detected TaskGroup Dependency wrapping unrecognized task. '
                        'TaskGroup Dependencies must be added to the TaskGroup. '
                    )
                edges.append((arg.task, task))
        try:
            for task in args:
                for arg in task.args:
                    check_dependency(arg)
                for key in task.kwargs:
                    check_dependency(task.kwargs[key])
            for edge in edges:
                self.graph.add_edge(*edge)
            if exc := self.verify_constraints():
                raise exc
        except TaskGroup.Exception as e:
            for edge in edges:
                self.graph.remove_edge(*edge)
            self.tasks.difference_update(args)
            self.graph.remove_nodes_from(args)
            raise e

    def remove_tasks(self, *args):
        self.tasks.difference_update(args)
        self.graph.remove_nodes_from(args)
    def verify_constraints(self) -> None | TaskGroup.Exception:
        if not networkx.is_directed_acyclic_graph(self.graph):
            return TaskGroup.Exception(
                'Cycle detected. '
                'Ordering constraints must not introduce cycles. '
                'A TaskGroup must be a directed acyclic graph.')


class Task:
    """
    A Task is the basic unit of execution.

    Usage:

    Specify the function to run in a task thread by passing the "target" argument as
    either the first argument in the argument list or as a keyword argument.

    ```py
    Task(lambda: print("Hello!"))
    # or 
    Task(target = lambda: print("Hello!"))
    ```

    Give the Task a name using the "name" parameter

    ```py
    task = Task(name = "pass")
    assert str(task) == "Task[pass]"
    ```

    Note:

    Each task instance has a unique id. Each thread started by a task is assigned a
    task-unique id that is stored on the thread object. The task id is also stored on
    the thread object. This is used by utilities in the test suite to track task/thread
    invocations during a unit test.

    ```py
    task = Task()
    task.id # task instance id
    task.start()
    task.thread # thread instance
    task.thread.id # thread instance id
    task.thread.task_id # task instance id
    ```
    """

    class Exception(Exception):
        pass

    class Thread(threading.Thread):
        count = itertools.count(0) # not sure what maximum value is, internet suggests infinite
        lock = threading.Lock()
        def __init__(self, task: Task, *args, **kwargs):
            super().__init__(*args, **kwargs)
            with Task.Thread.lock:
                self.id = next(Task.Thread.count)
            self.name = f"TaskThread-{self.id}"
            self.task_id = task.id

    def __init__(self, target = None, name = None, args = list(), kwargs = dict()):
        self.id = id(self)
        self.target = target if target else lambda: None
        self.args = args
        self.kwargs = kwargs
        if name:
            self.name = name
        elif self.target.__name__ != '<lambda>':
            self.name = self.target.__name__
        else:
            self.name = f"lambda:{self.id}"
    def __str__(self):
        return f"Task[{self.name}]"
    def start(self):
        self.thread = Task.Thread(task=self, target=self.target,args=(),kwargs={})
        print(f"starting [Task: {self.id}] [Thread: {self.thread.id}]")
        self.thread.start()
    def wait(self, timeout = None):
        self.thread.join(timeout)
    def set_args(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


