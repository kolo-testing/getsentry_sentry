from datetime import datetime

import click
import orjson

from sentry.runner.decorators import configuration


@click.command()
@click.option(
    "--generate-empty-task",
    default=False,
    is_flag=True,
    help="If true, will generate a mini task to spawn with logs",
)
@configuration
def task_worker(generate_empty_task) -> None:
    from sentry.taskworker.config import taskregistry
    from sentry.taskworker.models import PendingTasks

    if generate_empty_task:
        PendingTasks(
            topic="foobar",
            task_name="foo_the_bars",
            parameters=orjson.dumps({"args": [], "kwargs": {}}),
            task_namespace="hackweek",
            partition=1,
            offset=1,
            received_at=datetime.now(),
            state=PendingTasks.States.PENDING,
            deadletter_at=datetime.now(),
            processing_deadline=datetime.now(),
        ).save()

    from sentry.taskworker.worker import Worker

    namespace = taskregistry.create_namespace("hackweek", "foobar", "barfoo", None)

    # Sample event with a task execution, remove when we have some actual tasks
    @namespace.register("foo_the_bars", idempotent=None, deadline=None, retry=None)
    def foo_the_bars(*args, **kwargs):
        click.echo(args)
        click.echo(kwargs)

    Worker(namespace="hackweek").start()
