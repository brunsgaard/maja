from __future__ import absolute_import

from collections import defaultdict
from collections import namedtuple
from googleapiclient import discovery
from itertools import groupby
from oauth2client import file
from random import shuffle
from termcolor import colored

import datetime
import httplib2
import json
import re
import requests
import sys
import pytz


__author__ = 'jonas.brunsgaard@gmail.com (Jonas Brunsgaard)'


class DoodlePage(object):

    Entry = namedtuple('Entry', ['date', 'name'])

    def __init__(self, url):
        self.url = url
        self.data = self._fetch_json(self.url)

    @staticmethod
    def _fetch_json(url):
        resp = requests.get(url)
        pattern = '.*extend\(true, doodleJS.data, ({"poll":.*})\);'
        match = re.search(pattern, resp.text)
        return json.loads(match.groups()[0])

    @staticmethod
    def parse_date(datestring):
        m, d, y = map(int, datestring[3:].split('/'))
        return datetime.date(2000+y, m, d)

    def entries(self):
        dates = [self.parse_date(d) for d in self.data['poll']['optionsText']]
        participants = self.data['poll']['participants']
        for p in participants:
            mapping = zip(dates, p['preferences'])
            dates_filtered = (date for (date, char) in mapping if char == 'y')
            for date in dates_filtered:
                yield self.Entry(date, p['name'].title())


class TGWorkShift(object):

    Shift = namedtuple('Shift', ['date', 'text', 'start', 'end'])
    open_ = '16:00', '21:30'
    open_saturday = '13:00', '17:00'

    def __init__(self, url):
        self.doodle = list(DoodlePage(url).entries())
        self.entries = list(self.parse_doodle_entries())

    @staticmethod
    def format_names(names):
        return ' &'.join(', '.join(names).rsplit(',', 1))

    def parse_doodle_entries(self):
        entries = sorted(self.doodle)
        for date, sub_iter in groupby(entries, key=lambda t: t[0]):
            names = [e.name for e in sub_iter]
            shuffle(names)
            text = self.format_names(names)
            start, end = self.open_
            # If Saturday
            if date.weekday() == 5:
                start, end = self.open_saturday
            yield self.Shift(date, text, start, end)

    def __str__(self):
        res = []
        for date, text, start, end in self:
            date = '{}/{}'.format(date.day, date.month)
            res.append('{:<3} {}-{:<6} {}'.format(date, start, end, text))
        return '\n'.join(res)

    def __iter__(self):
        for e in self.entries:
            yield e

    def list_entries(self):
        for n, t in enumerate(self.entries):
            date, text, start, end = t
            date_str = u'{}/{}'.format(date.day, date.month)
            str_entry = (u'{:<4} - {:<4} {}-{:<6} {}'.format(
                u'({})'.format(n), date_str, start, end, text))
            if date.weekday() == 5:
                str_entry = colored(str_entry, 'magenta')
            print(str_entry)

    def append_text_to_entry(self, date, text, start, end):
        text = '{}{}'.format(text, raw_input(text))
        return self.Shift(date, text, start, end)

    def overwrite_text_to_entry(self, date, text, start, end):
        return self.Shift(date, raw_input('New text: '), start, end)

    def modify_entry(self):

        # pick an entry
        while True:
            input_ = raw_input('Pick entry: ')
            try:
                n = int(input_)
                entry = self.entries[n]
                break
            except:
                print('Come on Maja, that is not a valid entry, try again')

        # choose operation
        op = None
        while op not in ['a', 'o']:
            op = raw_input('Overwrite or append text? (o/a): ')
            if op == 'a':
                self.entries[n] = self.append_text_to_entry(*entry)
            if op == 'o':
                self.entries[n] = self.overwrite_text_to_entry(*entry)


class CalendarPusher(object):

    def __init__(self):
        storage = file.Storage('calendar' + '.dat')
        credentials = storage.get()
        http = credentials.authorize(http=httplib2.Http())
        self.cal = discovery.build('calendar', 'v3', http=http)
        self.events = defaultdict(list)

        # Events
        # {
        #     '2015-10-29': '$id'
        # }

        page_token = None
        while True:

            event_list = self.cal.events().list(
                calendarId='primary',
                pageToken=page_token
            ).execute()
            for e in event_list['items']:
                id_, date = e['id'], e['start'].get('dateTime', None)
                if date is None:
                    self.cal.events().delete(
                        calendarId='primary',
                        eventId=id_).execute()
                    continue

                y, m, d = map(int, date[:10].split('-'))
                date = datetime.date(y, m, d)
                self.events[date].append(id_)

            page_token = event_list.get('nextPageToken')
            if not page_token:
                break

    def clean_date(self, date):
        for id_ in self.events[date]:
            self.cal.events().delete(
                calendarId='primary', eventId=id_).execute()

    def push_entry(self, date, text, start, end):
        self.clean_date(date)
        cop = pytz.timezone('Europe/Copenhagen')
        start_hour, start_minute = [int(o) for o in start.split(':')]
        end_hour, end_minute = [int(o) for o in end.split(':')]
        loc_dt_start = cop.localize(datetime.datetime(
            date.year, date.month, date.day, start_hour, start_minute, 0, 0))
        loc_dt_end = cop.localize(datetime.datetime(
            date.year, date.month, date.day, end_hour, end_minute, 0, 0))
        data = {
            'summary': text,
            'start': {'dateTime': '{}'.format(loc_dt_start.isoformat())},
            'end': {'dateTime': '{}'.format(loc_dt_end.isoformat())},
        }
        return self.cal.events().insert(
            calendarId='primary', body=data).execute()


if __name__ == "__main__":
    url = sys.argv[1]
    shifts = TGWorkShift(url)
    cal = CalendarPusher()

    shifts.list_entries()
    # while True:
    #     input_ = raw_input('Do you want to modify the entries? (y/n): ')
    #     if input_ == 'y':
    #         shifts.modify_entry()
    #         shifts.list_entries()
    #     elif input_ == 'n':
    #         break
    #     else:
    #         print('What, Try again')

    while True:
        input_ = raw_input('Do You want to post the entries to the'
                           ' google calender? (y/n): ')
        if input_ == 'y':
            for shift in shifts:
                cal.push_entry(*shift)
                sys.stdout.write('.')
                sys.stdout.flush()
            print('\nDone')
            break
        elif input_ == 'n':
            print('Abort!!')
            break
        else:
            print('What, Try again')
