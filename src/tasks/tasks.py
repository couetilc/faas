
class TaskGroup:
    def __init__():
        # TODO: manage stdout and stderr for all child tasks.
        # TODO: create some kind of cancel Event, or perhaps a Queue.
        pass
    def __str__(self):
        # TODO: print the TaskGraph as a mermaid diagram representation.
        pass
    def start():
        # TODO: start each start task
        # TODO: store start time of task graph
        # TODO: store end time of task graph
        pass
    def cancel():
        # TODO: will cancel all tasks in the graph
        pass
    def wait():
        # TODO: will wait for all tasks in the graph to complete
        pass
    def set_stdout():
        # TODO: will set stdout file for task group
        pass
    def set_stderr():
        # TODO: will set stderr file for task group
        pass
    def poll():
        # TODO: returns true if still executing, false otherwise (I think this is the convention? I could ask AI for suggestion for this API)
        pass
    def add_precedence():
        # TODO: adds an ordering constraint, arguments proceed from left-to-right in
        # diminishing precedence
        # TODO: raise error if port_ready and ssh_ready have not been added as tasks.
        pass


class Task:
    class Exception(Exception):
        pass
    def __init__(self, name = None):
        self.name = name
        if self.name == None:
            self.name = self.__class__.__name__
    def target(self):
        raise Task.Exception(
            'subclasses of class "Task" MUST implement method "target"')
    def start():
        self.thread = threading.Thread(target=self.target,args=(),kwargs={})


class SleepTask(Task):
    def __init__(self, sleep_for):
        self.sleep_for = sleep_for
        super().__init__(f"sleep for {sleep_for}s")

