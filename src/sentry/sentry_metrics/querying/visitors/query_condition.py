from collections.abc import Mapping, Sequence

from snuba_sdk import BooleanCondition, BooleanOp, Column, Condition, Op
from snuba_sdk.expressions import ScalarType

from sentry.api.serializers import bulk_fetch_project_latest_releases
from sentry.models.project import Project
from sentry.sentry_metrics.querying.data.modulation.modulator import Modulator, find_modulator
from sentry.sentry_metrics.querying.errors import LatestReleaseNotFoundError
from sentry.sentry_metrics.querying.types import QueryCondition
from sentry.sentry_metrics.querying.visitors.base import QueryConditionVisitor, TVisited


class LatestReleaseTransformationVisitor(QueryConditionVisitor[QueryCondition]):
    """
    Visitor that recursively transforms all the conditions in the form `release:latest` by transforming them to
    `release IN [x, y, ...]` where `x` and `y` are the latest releases belonging to the supplied projects.
    """

    def __init__(self, projects: Sequence[Project]):
        self._projects = projects

    def _visit_condition(self, condition: Condition) -> QueryCondition:
        if not isinstance(condition.lhs, Column):
            return condition

        if not (
            condition.lhs.name == "release"
            and isinstance(condition.rhs, str)
            and condition.rhs == "latest"
        ):
            return condition

        latest_releases = bulk_fetch_project_latest_releases(self._projects)
        if not latest_releases:
            raise LatestReleaseNotFoundError(
                "Latest release(s) not found for the supplied projects"
            )

        return Condition(
            lhs=condition.lhs,
            op=Op.IN,
            rhs=[latest_release.version for latest_release in latest_releases],
        )


class TagsTransformationVisitor(QueryConditionVisitor[QueryCondition]):
    """
    Visitor that recursively transforms all conditions to work on tags in the form `tags[x]`.
    """

    def __init__(self, check_sentry_tags: bool):
        self._check_sentry_tags = check_sentry_tags

    def _visit_condition(self, condition: Condition) -> QueryCondition:
        if not isinstance(condition.lhs, Column):
            return condition

        # We assume that all incoming conditions are on tags, since we do not allow filtering by project in the
        # query filters.
        tag_column = f"tags[{condition.lhs.name}]"
        sentry_tag_column = f"sentry_tags[{condition.lhs.name}]"

        if self._check_sentry_tags:
            tag_column = f"tags[{condition.lhs.name}]"
            # We might have tags across multiple nested structures such as `tags` and `sentry_tags` for this reason
            # we want to emit a condition that spans both.
            return BooleanCondition(
                op=BooleanOp.OR,
                conditions=[
                    Condition(lhs=Column(name=tag_column), op=condition.op, rhs=condition.rhs),
                    Condition(
                        lhs=Column(name=sentry_tag_column),
                        op=condition.op,
                        rhs=condition.rhs,
                    ),
                ],
            )
        else:
            return Condition(lhs=Column(name=tag_column), op=condition.op, rhs=condition.rhs)


class MappingTransformationVisitor(QueryConditionVisitor[QueryCondition]):
    """
    Visitor that recursively transforms all conditions whose `key` matches one of the supplied mappings. If found,
    replaces it with the mapped value.
    """

    def __init__(self, mappings: Mapping[str, str]):
        self._mappings = mappings

    def _visit_condition(self, condition: Condition) -> QueryCondition:
        if not isinstance(condition.lhs, Column):
            return condition

        return Condition(
            lhs=Column(name=self._mappings.get(condition.lhs.key, condition.lhs.name)),
            op=condition.op,
            rhs=condition.rhs,
        )


class ProjectToProjectIDTransformationVisitor(QueryConditionVisitor[QueryCondition]):
    """
    Visitor that transforms all project name conditions in the query to project IDs. Initial
    use case of this is to enable the front-end to query projects directly instead of by id
    """

    def __init__(self, projects: Sequence[Project]):
        self._projects = projects

    def _visit_condition(self, condition: Condition) -> QueryCondition:
        if (
            isinstance(condition.lhs, Column)
            and condition.lhs.name == "project"
            and isinstance(condition.rhs, str)
        ):
            return Condition(
                lhs=Column(name="project_id"),
                op=condition.op,
                rhs=self._extract_project_id(condition.rhs),
            )

        return condition

    def _extract_project_id(self, project_slug: str) -> str:
        for project in self._projects:
            if project.slug == project_slug:
                return project.id


class ModulatorConditionVisitor(QueryConditionVisitor):
    def __init__(self, projects: Sequence[Project], modulators: Sequence[Modulator]):
        self._projects = projects
        self.modulators = modulators
        self.applied_modulators = []

    def _visit_condition(self, condition: Condition) -> TVisited:
        lhs = condition.lhs
        rhs = condition.rhs

        if isinstance(lhs, Column):
            modulator = find_modulator(self.modulators, lhs.name)
            if modulator:
                new_lhs = Column(modulator.to_key)
                self.applied_modulators.append(modulator)

                if isinstance(rhs, ScalarType):
                    new_rhs = modulator.modulate(rhs, self._projects)
                    return Condition(lhs=new_lhs, op=condition.op, rhs=new_rhs)

        return condition

    def _visit_boolean_condition(self, boolean_condition: BooleanCondition) -> TVisited:
        conditions = []
        for condition in boolean_condition.conditions:
            conditions.append(self.visit(condition))

        return BooleanCondition(op=boolean_condition.op, conditions=conditions)
