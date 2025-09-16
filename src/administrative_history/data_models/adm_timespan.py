from pydantic import BaseModel, model_validator, model_serializer
from typing import List, Union, Optional

from datetime import datetime, timedelta

#############################
# Models to store timespans #
#############################

class TimeSpan(BaseModel):
    start: datetime
    end: datetime
    middle: Optional[datetime] = None  # Middle will be calculated during validation

    @model_validator(mode='before')
    def check_end_after_start(cls, values):
        """Check that end date is after start date."""
        start = values.get('start')
        end = values.get('end')
        middle = values.get('middle')

        if start and end and end <= start:
            raise ValueError('End date must be after the start date.')
        
        if middle:
            raise ValueError('Timespan middle attribute is created automatically and should not be passed explicitly during initialization.')

        return values
    
    @model_validator(mode='after')
    def set_middle(cls, model):
        """Set the middle date as the rounded-up midpoint between start and end."""
        delta = model.end - model.start
        half = delta / 2

        middle = model.start + half

        # Round up to the next day if time is not midnight
        if middle.time() != datetime.min.time():
            middle = (middle + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        model.middle = middle
        return model
    
    @model_serializer(mode="plain")
    def serializer(self):
        # Do not serialize timespan middle attribute - it should be created automatically by model initialization.
        return {
            "start": self.start,
            "end": self.end
        }
    
    def update_middle(self):
        # Updated middle to be in half between self.start and self.end
        delta = self.end - self.start
        half = delta / 2
        self.middle = self.start + half
        return
    
    # Magic method for "in" operator
    def __contains__(self, to_compare: Union[datetime, "TimeSpan"]) -> bool:
        """
        Checks whether a date or another TimeSpan is fully contained within this TimeSpan.

        Parameters:
            other (datetime | TimeSpan): A single date or another timespan to check.

        Returns:
            bool: True if the date or entire timespan is within this one.
        """
        if isinstance(to_compare, datetime):
            # The timespan is implemented as a semi-closed interval: [start, end)
            # It has a consequence for downstream classes and functions,
            # e.g. out of states state1 and state2 with timespans (date_a, date_b), (date_b, date_c),
            # only state2 is assumed to "exist" at the moment date_b.
            return self.start <= to_compare < self.end # If argument to compare is a datetime
        elif isinstance(to_compare, TimeSpan):
            return self.start <= to_compare.start <= self.end and self.start <= to_compare.end <= self.end # If argument to compare is a timestamp, split it to 2 __contains__ comparisons for timestamp start and end.
        return to_compare in self.interval
    
    def __str__(self):
        return f"({self.start.date()}, {self.end.date()})"

class TimeSpanRegistry(BaseModel):
    """
    A model to store all periods between two sequential administrative changes.
    """
    registry: List[TimeSpan] 
