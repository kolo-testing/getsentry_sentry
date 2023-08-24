import {createContext, useEffect, useMemo, useRef, useState} from 'react';
import styled from '@emotion/styled';
import sortBy from 'lodash/sortBy';

import {ModalRenderProps} from 'sentry/actionCreators/modal';
import {t} from 'sentry/locale';
import {createFuzzySearch, Fuse} from 'sentry/utils/fuzzySearch';

import {OmniAction, OmniSection} from '../types';
import {useOmniSearchState} from '../useOmniState';

import {OmniResults} from './results';

export const OnmniSearchInputContext = createContext<
  React.Dispatch<React.SetStateAction<string>>
>(() => {});

function enabledActionsOnly(action: OmniAction) {
  return !action.hidden && !action.disabled;
}

function OmniSearchModal({Body, closeModal}: ModalRenderProps) {
  const searchState = useOmniSearchState();
  const [search, setSearch] = useState('');
  const fuse = useRef<Fuse<OmniAction>>();

  useEffect(() => {
    async function initializeFuse() {
      const {actions} = searchState;
      fuse.current = await createFuzzySearch(
        actions.filter(enabledActionsOnly).map(action => ({
          ...action,
          keywords: (action.keywords ?? []).concat(
            action.actionType === 'navigate' ? ['open', 'view', 'see', 'navigate'] : []
          ),
        })),
        {
          keys: ['label', 'keywords'],
          threshold: 0.8,
        }
      );
    }

    initializeFuse();
  }, [searchState]);

  const results = useMemo(() => {
    const {areas, areaPriority, focusedArea} = searchState;
    const actions = searchState.actions.filter(enabledActionsOnly);

    const hasSearch = search.length > 1;
    const searchResults = hasSearch
      ? fuse.current?.search(search).map(r => r.item)
      : actions;

    const topSearchResults: OmniSection[] = [
      {
        key: 'top-search-results',
        'aria-label': t('Top results'),
        actions:
          searchResults?.slice(0, 5).map(action => ({
            ...action,
            actionType: 'top-result',
            key: `top-result-${action.key}`,
          })) ?? [],
      },
    ];

    const searchResultsByArea: OmniSection[] = Object.values(areas)
      .sort(
        (a, b) =>
          areaPriority.findIndex(p => p === b.key) -
          areaPriority.findIndex(p => p === a.key)
      )
      .map(area => {
        return {
          key: area.key,
          label: area.key === focusedArea?.key ? null : area.label,
          actions: sortBy(
            searchResults?.filter(a => a.areaKey === area.key) ?? [],
            action => action.actionType
          ),
        };
      })
      .filter(area => area.actions?.length);

    const allResults = hasSearch
      ? [...topSearchResults, ...searchResultsByArea]
      : searchResultsByArea;

    return allResults;
  }, [search, searchState]);

  return (
    <Body>
      <Overlay>
        <OnmniSearchInputContext.Provider value={setSearch}>
          <OmniResults onAction={closeModal} results={results} />
        </OnmniSearchInputContext.Provider>
      </Overlay>
    </Body>
  );
}

export {OmniSearchModal};

const Overlay = styled('div')`
  width: 100%;
`;
