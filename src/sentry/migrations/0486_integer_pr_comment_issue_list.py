# Generated by Django 2.2.28 on 2023-06-13 22:27

import django.contrib.postgres.fields
from django.db import migrations

import sentry.db.models.fields.bounded
from sentry.new_migrations.migrations import CheckedMigration


class Migration(CheckedMigration):
    # This flag is used to mark that a migration shouldn't be automatically run in production. For
    # the most part, this should only be used for operations where it's safe to run the migration
    # after your code has deployed. So this should not be used for most operations that alter the
    # schema of a table.
    # Here are some things that make sense to mark as post deployment:
    # - Large data migrations. Typically we want these to be run manually by ops so that they can
    #   be monitored and not block the deploy for a long period of time while they run.
    # - Adding indexes to large tables. Since this can take a long time, we'd generally prefer to
    #   have ops run this and not block the deploy. Note that while adding an index is a schema
    #   change, it's completely safe to run the operation after the code has deployed.
    is_post_deployment = False
    checked = False

    dependencies = [
        ("sentry", "0485_remove_scheduled_job"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pullrequestcomment",
            name="group_ids",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=sentry.db.models.fields.bounded.BoundedBigIntegerField(),
                default=None,
                size=None,
            ),
            preserve_default=False,
        ),
    ]
