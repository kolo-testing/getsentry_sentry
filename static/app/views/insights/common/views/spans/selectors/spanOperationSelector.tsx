import type {Location} from 'history';
import omit from 'lodash/omit';

import SelectControl from 'sentry/components/forms/controls/selectControl';
import {t} from 'sentry/locale';
import {browserHistory} from 'sentry/utils/browserHistory';
import EventView from 'sentry/utils/discover/eventView';
import {DiscoverDatasets} from 'sentry/utils/discover/types';
import {EMPTY_OPTION_VALUE} from 'sentry/utils/tokenizeSearch';
import {useLocation} from 'sentry/utils/useLocation';
import {useSpansQuery} from 'sentry/views/insights/common/queries/useSpansQuery';
import {buildEventViewQuery} from 'sentry/views/insights/common/utils/buildEventViewQuery';
import {DefaultEmptyOption} from 'sentry/views/insights/common/views/spans/selectors/emptyOption';
import {SpanMetricsField} from 'sentry/views/insights/spanFields';
import {ModuleName} from 'sentry/views/insights/types';

const {SPAN_OP} = SpanMetricsField;

type Props = {
  value: string;
  moduleName?: ModuleName;
  spanCategory?: string;
};

export function SpanOperationSelector({
  value = '',
  moduleName = ModuleName.ALL,
  spanCategory,
}: Props) {
  // TODO: This only returns the top 25 operations. It should either load them all, or paginate, or allow searching
  //
  const location = useLocation();
  const eventView = getEventView(location, moduleName, spanCategory);

  const {data: operations} = useSpansQuery<{'span.op': string}[]>({
    eventView,
    initialData: [],
    referrer: 'api.starfish.get-span-operations',
  });

  const options = [
    {value: '', label: 'All'},
    ...(operations ?? [])
      .filter(datum => Boolean(datum))
      .map(datum => {
        if (datum[SPAN_OP] === '') {
          return {
            value: EMPTY_OPTION_VALUE,
            label: <DefaultEmptyOption />,
          };
        }
        return {
          value: datum[SPAN_OP],
          label: datum[SPAN_OP],
        };
      }),
  ];

  return (
    <SelectControl
      inFieldLabel={`${t('Operation')}:`}
      value={value}
      options={options ?? []}
      onChange={newValue => {
        browserHistory.push({
          ...location,
          query: {
            ...location.query,
            [SPAN_OP]: newValue.value,
          },
        });
      }}
    />
  );
}

function getEventView(location: Location, moduleName: ModuleName, spanCategory?: string) {
  const query = buildEventViewQuery({
    moduleName,
    location: {...location, query: omit(location.query, SPAN_OP)},
    spanCategory,
  }).join(' ');
  return EventView.fromNewQueryWithLocation(
    {
      name: '',
      fields: [SPAN_OP, 'count()'],
      orderby: '-count',
      query,
      dataset: DiscoverDatasets.SPANS_METRICS,
      version: 2,
    },
    location
  );
}
