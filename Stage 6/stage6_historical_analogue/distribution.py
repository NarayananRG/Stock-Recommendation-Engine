import math
from .errors import Stage6HistoricalAnalogueError
def quantile(values,p):
 if not values:return None
 ordered=sorted(values);index=(len(ordered)-1)*p;lower=math.floor(index);upper=math.ceil(index)
 return ordered[lower] if lower==upper else ordered[lower]+(ordered[upper]-ordered[lower])*(index-lower)
def distribution(values,unit):
 if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):raise Stage6HistoricalAnalogueError("HISTORICAL_ANALOGUE_NONFINITE_VALUE")
 ordered=sorted(values);count=len(ordered)
 if not count:return {"unit":unit,"count":0,"median":None,"mean":None,"standard_deviation":None,"p10":None,"p25":None,"p75":None,"p90":None,"minimum":None,"maximum":None}
 mean=math.fsum(ordered)/count;sd=math.sqrt(math.fsum((x-mean)**2 for x in ordered)/count)
 return {"unit":unit,"count":count,"median":quantile(ordered,.5),"mean":mean,"standard_deviation":sd,"p10":quantile(ordered,.1),"p25":quantile(ordered,.25),"p75":quantile(ordered,.75),"p90":quantile(ordered,.9),"minimum":ordered[0],"maximum":ordered[-1]}
