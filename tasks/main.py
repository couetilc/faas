
# TODO: some type of TaskThread class
# - needs to specify dependencies:
#   - parent dependencies: thread does not execute until condition from parent is satisfied.
#   - child dependencies: communicate conditions somehow
# - holds reference to a cancel event used by each TaskThread
# - maybe Queue for communication between parents/childs? (instead of single Event, could have queue that receives event messages, and also shuts down when parent finishes)
#   - queue's can send messages: (like "ready")
#   - queue's can end. See "Queue.shutdown()"
# - timing tracking (start time, end time, duration)
# - automatic resource cleanup after completion.
# - handles interrupts well and across all tasks
# - task's childrens execute concurrently.

class TaskGraph:
    def __init__():
        # TODO: manage stdout and stderr for all child tasks.
        # TODO: create some kind of cancel Event, or perhaps a Queue.
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
    def add_start_task():
        # TODO: adds a task to the start task list
        pass
    def poll():
        # TODO: returns true if still executing, false otherwise (I think this is the convention? I could ask AI for suggestion for this API)
        pass
    def __str__(self):
        # TODO: print the TaskGraph as a mermaid diagram representation.
        pass

class Task:
    def __init__():
        # TODO: create a thread.
        pass
    def target():
        # TODO: target is the function run in the thread
        pass
    def depends_on():
        # TODO: register a task dependency
        pass

# TODO graph stuff edge-cases:
# - make sure no cycles? What would this even look like?
# - make sure tasks cannot depend on itself?
# - any other gotchas from literature or otherwise?

# My test TaskGroups will be simpler:
# First things first:
#   task = Task(name: 'sleep for 1s')
#   task.run()
#   task.wait()
# Then introduce TasksGroup:
#   group = TaskGroup(name: 'sleeps')
#   task = Task(name: 'sleep for 1s')
#   group.add_start_task(task)
#   group.run()
#   group.wait()
# Then introduce dependencies:
#   group = TaskGroup(name: 'sleeps')
#   task1 = Task(name: 'sleep for 1s')
#   task2 = Task(name: 'sleep for 2s')
#   group.add_start_task(task)
#   task2.depends_on(task1)
#   group.run()
#   group.wait()

# The first TaskGroup I will implement is:
# TaskGroup(name: 'run tests once')
# - Task(name: 'create overlay image')
# - Task(name: 'start qemu vm')
# - Task(name: 'wait until port is ready')
# - Task(name: 'wait until ssh is ready')
# - Task(name: 'rsync files once')
# - Task(name: 'run tests once')
# def main():
#   group = TaskGroup(name: 'run tests once')
#   task1 = Task(name: 'create overlay image')
#   task2 = Task(name: 'start qemu vm')
#   task3 = Task(name: 'wait until port is ready')
#   task4 = Task(name: 'wait until ssh is ready')
#   task5 = Task(name: 'rsync files once')
#   task6 = Task(name: 'run tests once')
#   group.add_start_task(task1)
#   task2.depends_on(task1)
#   task3.depends_on(task2)
#   task4.depends_on(task3)
#   task5.depends_on(task4)
#   task6.depends_on(task5)
#   group.set_stdout(sys.stdout)
#   group.set_stderr(sys.stderr)
#   group.run()
#   group.wait()
#   print(group.stdout)
#   print(group.stderr)
