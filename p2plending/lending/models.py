from django.db import models
from django.contrib.auth.models import User
from django.conf.global_settings import LANGUAGES 
from django.utils.timezone import now
import datetime
import uuid


LOAN_PERIOD = 14 # In Days
MEDIA_TYPES = ( ("book","Book"), ("periodical","Periodical") )
ITEM_STATUS = ( 
    ("available","Available"), 
    ("on-loan","On Loan"), 
    ("unavailable","Unavailable"), 
    ("reserved","Reserved")
)
LOAN_STATUS = (
    ("requested","Requested"),
    ("available","Available for Borrower Pickup"),
    ("on-loan","On Loan"),
    ("returned","Returned / Availabe for Lender Pickup"),
    ("complete","Returned to Lender"),
    ("lost","Item Lost"),
    ("return-issue","Item Returned in poor quality"),
)
REQUEST_STATUS = (
    ("requested","Requested"),
    ("canceled", "Canceled"),
    ("complete", "Completed"),
)
NOTIFY_BY = (("email","email"),("sms","sms"))

class Location(models.Model):
    name = models.CharField(max_length=255) 
    lat = models.FloatField()
    lng = models.FloatField()

    def __str__(self):
        return self.name

class Profile(models.Model):
    user = models.OneToOneField(User,on_delete=models.SET_NULL,null=True) 
    preferred_language = models.CharField(max_length=16,choices=LANGUAGES,blank=True,null=True)  
    library_card = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=64,blank=True)
    email = models.EmailField(null=True,blank=True)
    notify_by = models.CharField(max_length=8,choices=NOTIFY_BY,blank=True,null=True)
    primary_location = models.ForeignKey(Location,on_delete=models.SET_NULL,null=True)


    def __str__(self):
        return "%s (%s)" % (self.name, self.library_card)

    def items_on_loan(self):
        return self.loan_set.filter(status="on-loan")

    def titles_requested(self):
        return self.titlerequest_set.filter(status="requested")

class Title(models.Model):
    language = models.CharField(max_length=16,choices=LANGUAGES,blank=True,null=True)  
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255,blank=True,null=True)
    publish_year = models.IntegerField(blank=True,null=True)
    cover_image = models.ImageField(null=True,upload_to='covers/%Y/%m/%d/',blank=True)
    media_type = models.CharField(max_length=8,choices=MEDIA_TYPES)
    description = models.TextField(blank=True)
    meta_data = models.TextField(blank=True)

    def active_items(self):
        return self.item_set.exclude(status__in=("private","unavailable"))

    def available_items(self):
        return self.item_set.filter(status="available")

    def get_next_item(self):
        try:
            return self.available_items()[0]
        except IndexError:
            return None

    def create_request(self,requester):
        title_request = TitleRequest(
            requester = requester,
            title = self,
            request_date = now(),
            loan = None,
            status = "requested",
        )
        title_request.save()
        return title_request

    def queued_requests(self):
        return self.titlerequest_set.filter(status="requested").order_by("request_date")

    def process_next_request(self):
        # TODO wrap this in a database transaction
        if not self.available_items().exists():
            return None
        try:
            # Get next queued request by date
            next_request = self.queued_requests()[0]
            return next_request.process_request()
        except IndexError:
            return None

    def __str__(self):
        return "%s (%s - %s)" % (self.title,self.media_type,self.language)
   
class Item(models.Model):
    guid = models.CharField(max_length=255,blank=True)
    title = models.ForeignKey(Title,on_delete=models.CASCADE)   
    owner = models.ForeignKey(Profile,on_delete=models.CASCADE)
    status = models.CharField(max_length=16,choices=ITEM_STATUS,default="available")
    date_added = models.DateTimeField(blank=True)

    def save(self,*args,**kwargs):
        if not self.guid:
            self.guid = uuid.uuid4().hex
        if not self.date_added:
            self.date_added = now()
        super(Item,self).save(*args,**kwargs)

    def create_loan(self,borrower, renewal_of=None):
        if self.status != "available": return None
        # TODO do this in a db transaction
        loan = Loan(
            item = self,
            borrower = borrower,
            start_date = now(),
            due_date = now() + datetime.timedelta(days=LOAN_PERIOD),
            renewal_of = renewal_of,
            status = "requested"
        )
        loan.save()
        self.status = "reserved"
        self.save()
        return loan

    def __str__(self):
        return "%s (%s) [%s]" % (self.title, self.guid, self.status)
      
class Loan(models.Model):
    borrower = models.ForeignKey(Profile,on_delete=models.SET_NULL,null=True)
    item = models.ForeignKey(Item,on_delete=models.SET_NULL,null=True)
    start_date = models.DateTimeField()
    due_date = models.DateTimeField()
    renewal_of = models.ForeignKey("self",blank=True,null=True,on_delete=models.SET_NULL)
    status = models.CharField(max_length=16,choices=LOAN_STATUS,default="requested")
 
class TitleRequest(models.Model):
    requester = models.ForeignKey(Profile,on_delete=models.SET_NULL,null=True)  
    title = models.ForeignKey(Title,on_delete=models.CASCADE)
    request_date = models.DateTimeField()
    loan = models.ForeignKey(Loan,blank=True,null=True,on_delete=models.SET_NULL)
    status = models.CharField(max_length=255,default="pending",choices=REQUEST_STATUS)

    def process_request(self):
        next_item = self.title.get_next_item()
        if next_item != None:
            self.loan = next_item.create_loan(self.requester)
            self.status = "complete"
            self.save()
            return self.loan
        return None

    def cancel_request(self):
        self.status = "canceled"
        self.save()

    def __str__(self):
        return "%s requested by %s on %s (%s)" % (
            self.title.title[:32],
            self.requester.name,
            self.request_date,
            self.status
        )
