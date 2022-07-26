from locust import HttpUser, SequentialTaskSet, between, task


class LoadTest1(SequentialTaskSet):
    
    # curl http://localhost:5000/profile/file/vector -F response=deferred -F resource=@data/1.zip
    @task
    def send_profile_task_1(self):
        payload = {
            'response': 'deferred'
        }
        files = {
            'resource': open('/data/1.zip', 'rb')
        } 
        self.client.post("/profile/file/vector", data=payload, files=files, name="profile/file/vector")

class MicroservicesUser(HttpUser):
    wait_time = between(20, 30)  # how much time a user waits (seconds) to run another TaskSequence
    # [SequentialTaskSet]: [weight of the SequentialTaskSet]
    tasks = {
        LoadTest1: 100
    }
