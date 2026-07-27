import React from 'react'

import { cellText } from '../../domain/formatters.js'

const COUNTRY_FLAGS = {
  EM: '🌐',
  EMU: '🇪🇺',
  EU: '🇪🇺',
  Europe: '🇪🇺',
  France: '🇫🇷',
  Germany: '🇩🇪',
  Italy: '🇮🇹',
  Japan: '🇯🇵',
  Spain: '🇪🇸',
  UK: '🇬🇧',
  US: '🇺🇸',
  USA: '🇺🇸',
}

const COUNTRY_FACTORS = [
  ['margin', 'Margin'],
  ['profitability', 'Profit'],
  ['growth', 'Growth'],
  ['value', 'Value'],
  ['momentum', 'Momentum'],
]

export function countryFlag(value) {
  const text = cellText(value)
  return COUNTRY_FLAGS[text] || COUNTRY_FLAGS[text.toUpperCase()] || '🌐'
}

export function countryScoreWidth(value) {
  const number = Number.parseFloat(value)
  if (!Number.isFinite(number)) return '0%'
  return `${Math.max(0, Math.min(100, number * 10))}%`
}

function countryProfile(item) {
  const score = Number.parseFloat(item.score)
  const recommendation = cellText(item.recommendation).toLowerCase()
  if (recommendation.includes('positive') || score >= 6.6) {
    return { label: 'Positive', color: '#167768', soft: '#e7f3ef' }
  }
  if (recommendation.includes('negative') || score <= 4.2) {
    return { label: 'Negative', color: '#b33f55', soft: '#f8e7eb' }
  }
  return { label: 'Neutral', color: '#315d9f', soft: '#e9eef8' }
}

function CountryFactorBars({ item }) {
  return (
    <div className="tp-country-factors">
      {COUNTRY_FACTORS.map(([key, label]) => (
        <div className="tp-country-factor" key={key}>
          <span>{label}</span>
          <div className="tp-country-factor-track">
            <i style={{ width: countryScoreWidth(item[key]) }} />
          </div>
          <strong>{cellText(item[key])}</strong>
        </div>
      ))}
    </div>
  )
}

export function CountryRegionCard({ item }) {
  const profile = countryProfile(item)
  const flag = countryFlag(item.region)
  return (
    <div
      className="tp-country-card"
      style={{ '--country-color': profile.color, '--country-soft': profile.soft }}
    >
      <div className="tp-country-card-head">
        <div className="tp-country-title">
          <b>{flag}</b>
          <div>
            <span>{cellText(item.country_label)}</span>
            <strong>{cellText(item.region)}</strong>
          </div>
        </div>
        <em>{cellText(item.recommendation || profile.label)}</em>
      </div>
      <div className="tp-country-score-line">
        <strong>{cellText(item.score)}</strong>
        <span>rank #{cellText(item.rank)} / {cellText(item.最新月份)}</span>
      </div>
      <div className="tp-country-score-track" aria-label={`${item.region} country score`}>
        <i style={{ width: countryScoreWidth(item.score) }} />
      </div>
      <div className="tp-country-card-meta">
        <span>rank change {cellText(item.rank_delta)}</span>
        <span>{cellText(item.model)}</span>
      </div>
      <CountryFactorBars item={item} />
    </div>
  )
}

function SingleCountryTile({ item }) {
  const profile = countryProfile(item)
  const flag = countryFlag(item.country)
  return (
    <div
      className="tp-single-country-tile"
      style={{ '--country-color': profile.color, '--country-soft': profile.soft }}
    >
      <div className="tp-single-country-head">
        <span><b>{flag}</b>{cellText(item.country)}</span>
        <strong>#{cellText(item.rank)}</strong>
      </div>
      <small>{cellText(item.country_label)}</small>
      <div className="tp-single-country-score">
        <strong>{cellText(item.score)}</strong>
        <div className="tp-country-score-track">
          <i style={{ width: countryScoreWidth(item.score) }} />
        </div>
      </div>
    </div>
  )
}

export function SingleCountryBoard({ rows }) {
  if (!rows.length) return <div className="tp-empty">暂无单个国家分数</div>
  const [leader, ...rest] = rows
  const leaderProfile = countryProfile(leader)
  const leaderFlag = countryFlag(leader.country)
  return (
    <div className="tp-single-country-board">
      <div
        className="tp-country-leader"
        style={{ '--country-color': leaderProfile.color, '--country-soft': leaderProfile.soft }}
      >
        <div className="tp-country-card-head">
          <div className="tp-country-title">
            <b>{leaderFlag}</b>
            <div>
              <span>Top single country</span>
              <strong>{cellText(leader.country)}</strong>
            </div>
          </div>
          <em>#{cellText(leader.rank)}</em>
        </div>
        <div className="tp-country-score-line">
          <strong>{cellText(leader.score)}</strong>
          <span>{cellText(leader.country_label)} / {cellText(leader.最新月份)}</span>
        </div>
        <div className="tp-country-score-track" aria-label={`${leader.country} country score`}>
          <i style={{ width: countryScoreWidth(leader.score) }} />
        </div>
        <CountryFactorBars item={leader} />
      </div>
      <div className="tp-single-country-grid">
        {rest.map((item) => (
          <SingleCountryTile item={item} key={`${item.country}-${item.最新月份}`} />
        ))}
      </div>
    </div>
  )
}
