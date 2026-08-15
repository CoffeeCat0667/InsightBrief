# -*- coding: utf-8 -*-
from Core.models import RequestHeaders

from .guardian_news import GuardianNewsCrawler

__all__ = ["GuardianNewsCrawler", "RequestHeaders"]
